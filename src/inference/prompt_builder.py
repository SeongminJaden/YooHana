"""Prompt construction utilities for the AI Influencer inference pipeline.

Builds structured chat prompts (system / user messages) that respect the
persona definition and can be formatted via ``tokenizer.apply_chat_template``.
"""

from __future__ import annotations

from typing import Optional

from src.persona.character import Persona


class PromptBuilder:
    """Constructs chat-style prompts for caption generation, reply generation,
    and weekly content planning.

    Each ``build_*`` method returns a list of message dicts
    (``[{"role": ..., "content": ...}, ...]``) ready for
    ``tokenizer.apply_chat_template``.

    Parameters
    ----------
    persona:
        A :class:`Persona` instance that provides the system prompt,
        caption/reply instructions, and boundary information.
    """

    def __init__(self, persona: Persona) -> None:
        self._persona = persona

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _system_message(self) -> dict[str, str]:
        """Return the system-role message derived from the persona."""
        return {"role": "system", "content": self._persona.system_prompt}

    # ------------------------------------------------------------------
    # Caption prompt
    # ------------------------------------------------------------------

    def build_caption_prompt(
        self,
        topic: str,
        context: str = "",
    ) -> list[dict[str, str]]:
        """Build a chat prompt for Instagram caption generation.

        Parameters
        ----------
        topic:
            The topic or theme of the post (e.g. "카페 탐방").
        context:
            Optional context such as recent post captions to avoid
            repetition.  When provided it is prepended to the user
            instruction.

        Returns
        -------
        list[dict[str, str]]
            A list of message dicts suitable for
            ``tokenizer.apply_chat_template``.
        """
        instruction = self._persona.get_caption_instruction(topic)

        if context:
            instruction = (
                f"[최근 게시글 참고 – 내용이 겹치지 않도록 해줘]\n"
                f"{context}\n\n"
                f"{instruction}"
            )

        return [
            self._system_message(),
            {"role": "user", "content": instruction},
        ]

    # ------------------------------------------------------------------
    # Reply prompt
    # ------------------------------------------------------------------

    def build_reply_prompt(
        self,
        comment: str,
        post_caption: str = "",
    ) -> list[dict[str, str]]:
        """Build a chat prompt for replying to a follower comment.

        Parameters
        ----------
        comment:
            The follower comment text to reply to.
        post_caption:
            Optional caption of the original post for context.

        Returns
        -------
        list[dict[str, str]]
            A list of message dicts suitable for
            ``tokenizer.apply_chat_template``.
        """
        instruction = self._persona.get_reply_instruction(comment)

        if post_caption:
            instruction = (
                f"[원본 게시글 캡션]\n"
                f"{post_caption}\n\n"
                f"{instruction}"
            )

        return [
            self._system_message(),
            {"role": "user", "content": instruction},
        ]

    # ------------------------------------------------------------------
    # Planning prompt
    # ------------------------------------------------------------------

    def build_planning_prompt(
        self,
        recent_posts: list[str],
        season: str,
    ) -> list[dict[str, str]]:
        """Build a chat prompt for weekly content planning.

        Parameters
        ----------
        recent_posts:
            A list of recent post captions / summaries so the model can
            avoid repetition and keep a coherent content calendar.
        season:
            Current season string (``"spring"``, ``"summer"``,
            ``"autumn"``, ``"winter"``).

        Returns
        -------
        list[dict[str, str]]
            A list of message dicts suitable for
            ``tokenizer.apply_chat_template``.
        """
        # Build a numbered list of recent posts for context
        if recent_posts:
            recent_list = "\n".join(
                f"  {i}. {post}" for i, post in enumerate(recent_posts, 1)
            )
            recent_section = (
                f"[최근 게시글]\n{recent_list}\n\n"
                f"위 게시글과 내용이 겹치지 않도록 해줘.\n\n"
            )
        else:
            recent_section = ""

        # Map season to Korean for the instruction
        season_kr: dict[str, str] = {
            "spring": "봄",
            "summer": "여름",
            "autumn": "가을",
            "winter": "겨울",
        }
        season_name = season_kr.get(season, season)

        instruction = (
            f"{recent_section}"
            f"이번 주 인스타그램 콘텐츠 계획을 세워줘.\n\n"
            f"현재 계절: {season_name}\n\n"
            f"조건:\n"
            f"- {self._persona.name}의 캐릭터와 관심사에 맞는 주제\n"
            f"- 하루 최대 2개 게시글\n"
            f"- 각 게시글마다 주제, 시간대, 간단한 컨셉 설명 포함\n"
            f"- 계절감을 반영할 것\n"
            f"- 다양한 카테고리 (일상, 패션, 카페, 자기계발 등) 골고루\n"
            f"- 주말에는 좀 더 여유로운 콘텐츠\n\n"
            f"형식:\n"
            f"월요일:\n"
            f"  1. [시간대] 주제 - 컨셉 설명\n"
            f"  2. [시간대] 주제 - 컨셉 설명\n"
            f"화요일:\n"
            f"  ..."
        )

        return [
            self._system_message(),
            {"role": "user", "content": instruction},
        ]
