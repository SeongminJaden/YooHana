"""
Instagram authentication module using instagrapi.

Handles login, 2FA challenge resolution, and session persistence so that
subsequent runs can reuse an existing session without re-authenticating.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv
from instagrapi import Client
from instagrapi.exceptions import (
    BadPassword,
    ChallengeRequired,
    LoginRequired,
    TwoFactorRequired,
)

from src.utils.error_handler import (
    AuthenticationError,
    InstagramError,
)
from src.utils.logger import get_logger

logger = get_logger()

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _PROJECT_ROOT / "config" / "settings.yaml"


def _load_settings() -> dict:
    """Load and return the instagram section from settings.yaml."""
    if not _CONFIG_PATH.exists():
        raise InstagramError(f"Settings file not found: {_CONFIG_PATH}")
    with _CONFIG_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


class InstagramAuth:
    """Manage Instagram authentication with session caching.

    Credentials are loaded from environment variables
    (``INSTAGRAM_USERNAME``, ``INSTAGRAM_PASSWORD``).  An optional
    ``INSTAGRAM_2FA_SEED`` variable is supported for TOTP-based 2FA.

    Parameters
    ----------
    env_path : Path | str | None
        Path to a ``.env`` file.  Defaults to ``<project_root>/.env``.
    """

    def __init__(self, env_path: Optional[Path | str] = None) -> None:
        env_file = Path(env_path) if env_path else _PROJECT_ROOT / ".env"
        load_dotenv(dotenv_path=env_file)

        self._username: str = os.getenv("INSTAGRAM_USERNAME", "")
        self._password: str = os.getenv("INSTAGRAM_PASSWORD", "")

        if not self._username or not self._password:
            raise AuthenticationError(
                "INSTAGRAM_USERNAME and INSTAGRAM_PASSWORD must be set in the "
                "environment or .env file."
            )

        settings = _load_settings()
        ig_cfg = settings.get("instagram", {})
        session_filename = ig_cfg.get("session_file", "instagram_session.json")
        self._session_path: Path = _PROJECT_ROOT / session_filename

        self._2fa_seed: str = os.getenv("INSTAGRAM_2FA_SEED", "")

        logger.debug("InstagramAuth initialised for @{}", self._username)

    # ------------------------------------------------------------------
    # Session persistence
    # ------------------------------------------------------------------

    def save_session(self, client: Client, path: Optional[str] = None) -> None:
        """Save the client session to a JSON file for later reuse.

        Parameters
        ----------
        client : Client
            An authenticated instagrapi Client.
        path : str | None
            Override path for the session file.
        """
        target = Path(path) if path else self._session_path
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps(client.get_settings(), indent=2),
                encoding="utf-8",
            )
            logger.info("Session saved to {}", target)
        except (OSError, TypeError) as exc:
            raise InstagramError(
                f"Failed to save session to {target}: {exc}"
            ) from exc

    def load_session(self, path: Optional[str] = None) -> Client | None:
        """Try to restore a previously saved session.

        Parameters
        ----------
        path : str | None
            Override path for the session file.

        Returns
        -------
        Client | None
            An authenticated Client if the session is still valid,
            otherwise ``None``.
        """
        target = Path(path) if path else self._session_path
        if not target.exists():
            logger.debug("No session file found at {}", target)
            return None

        try:
            settings = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Corrupt session file {}: {}", target, exc)
            return None

        client = Client()
        client.set_settings(settings)

        # Validate the restored session by calling a lightweight endpoint.
        try:
            client.login(self._username, self._password)
            client.get_timeline_feed()
            logger.info("Session restored from {}", target)
            return client
        except LoginRequired:
            logger.warning("Saved session expired – re-login required.")
            return None
        except ChallengeRequired:
            logger.warning("Challenge required on session restore.")
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("Session restore failed: {}", exc)
            return None

    # ------------------------------------------------------------------
    # Login
    # ------------------------------------------------------------------

    def login(self) -> Client:
        """Perform a fresh login, handling 2FA and challenges.

        Returns
        -------
        Client
            An authenticated instagrapi Client.

        Raises
        ------
        AuthenticationError
            If login fails after handling known challenge types.
        """
        client = Client()
        try:
            client.login(self._username, self._password)
            logger.info("Login successful for @{}", self._username)
            return client

        except TwoFactorRequired:
            logger.info("2FA required for @{}", self._username)
            return self._handle_2fa(client)

        except ChallengeRequired:
            logger.warning("Challenge required for @{}", self._username)
            return self._handle_challenge(client)

        except BadPassword:
            raise AuthenticationError(
                f"Bad password for @{self._username}. "
                "Check INSTAGRAM_PASSWORD in your .env file."
            )

        except LoginRequired as exc:
            raise AuthenticationError(
                f"Login required but could not authenticate: {exc}"
            ) from exc

        except Exception as exc:  # noqa: BLE001
            raise AuthenticationError(
                f"Unexpected login error for @{self._username}: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # 2FA / challenge helpers
    # ------------------------------------------------------------------

    def _handle_2fa(self, client: Client) -> Client:
        """Handle two-factor authentication.

        If ``INSTAGRAM_2FA_SEED`` is set, the TOTP code is generated
        automatically.  Otherwise the user is prompted on stdin.
        """
        try:
            if self._2fa_seed:
                from instagrapi.mixins.totp import TOTPMixin  # type: ignore[import-untyped]

                totp = TOTPMixin()
                code = totp.totp_generate_code(self._2fa_seed)
                logger.debug("Generated TOTP code from seed.")
            else:
                code = input("Enter 2FA code: ").strip()

            client.login(
                self._username,
                self._password,
                verification_code=code,
            )
            logger.info("2FA login successful for @{}", self._username)
            return client

        except Exception as exc:  # noqa: BLE001
            raise AuthenticationError(f"2FA handling failed: {exc}") from exc

    @staticmethod
    def _handle_challenge(client: Client) -> Client:
        """Attempt to automatically resolve an Instagram challenge."""
        try:
            client.challenge_resolve_auto()
            logger.info("Challenge resolved automatically.")
            return client
        except Exception as exc:  # noqa: BLE001
            raise AuthenticationError(
                f"Could not resolve Instagram challenge: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def get_client(self) -> Client:
        """Return an authenticated Client, preferring a cached session.

        Tries ``load_session()`` first; falls back to ``login()`` and
        persists the new session on success.

        Returns
        -------
        Client
            An authenticated instagrapi Client ready for use.
        """
        client = self.load_session()
        if client is not None:
            return client

        logger.info("No valid session – performing fresh login.")
        client = self.login()
        self.save_session(client)
        return client
