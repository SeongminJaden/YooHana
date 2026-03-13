"""
Data cleaning utilities for collected Instagram captions.

Reads raw JSON files produced by :mod:`collector`, normalises text,
filters low-quality entries, deduplicates, and writes the result as a
single JSONL file ready for dataset construction.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from src.utils.logger import get_logger

logger = get_logger()

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class DataCleaner:
    """Clean and filter raw caption data for downstream training."""

    # Pre-compiled patterns for caption cleaning
    _RE_MENTION = re.compile(r"@[\w.]+")
    _RE_URL = re.compile(r"https?://\S+|www\.\S+")
    _RE_EXCESSIVE_HASHTAGS = re.compile(
        r"(?:#[\w\u0080-\uffff]+\s*){4,}"
    )
    _RE_SINGLE_HASHTAG = re.compile(r"#([\w\u0080-\uffff]+)")
    _RE_MULTI_WHITESPACE = re.compile(r"[ \t]+")
    _RE_MULTI_NEWLINES = re.compile(r"\n{3,}")

    # ------------------------------------------------------------------
    # Text-level cleaning
    # ------------------------------------------------------------------

    def clean_caption(self, text: str) -> str:
        """Clean a single caption string.

        Processing steps
        ----------------
        1. Remove ``@mentions``
        2. Remove URLs
        3. Remove *excessive* hashtag blocks (4+ consecutive hashtags)
        4. Convert remaining lone ``#hashtag`` to plain text
        5. Normalise whitespace (collapse multiple spaces / blank lines)
        6. Strip leading/trailing whitespace

        Parameters
        ----------
        text : str
            Raw caption text.

        Returns
        -------
        str
            Cleaned caption.
        """
        cleaned = text

        # 1. Remove @mentions
        cleaned = self._RE_MENTION.sub("", cleaned)

        # 2. Remove URLs
        cleaned = self._RE_URL.sub("", cleaned)

        # 3. Remove blocks of 4+ consecutive hashtags (spam / tag-stuffing)
        cleaned = self._RE_EXCESSIVE_HASHTAGS.sub("", cleaned)

        # 4. Turn remaining solo hashtags into plain words
        cleaned = self._RE_SINGLE_HASHTAG.sub(r"\1", cleaned)

        # 5. Normalise whitespace
        cleaned = self._RE_MULTI_WHITESPACE.sub(" ", cleaned)
        cleaned = self._RE_MULTI_NEWLINES.sub("\n\n", cleaned)

        # 6. Strip
        cleaned = cleaned.strip()

        return cleaned

    # ------------------------------------------------------------------
    # Collection-level filtering
    # ------------------------------------------------------------------

    @staticmethod
    def filter_quality(
        captions: list[dict],
        min_length: int = 20,
        max_length: int = 500,
    ) -> list[dict]:
        """Keep only captions within an acceptable length range.

        Parameters
        ----------
        captions : list[dict]
            Caption dicts (must contain a ``"text"`` key).
        min_length : int
            Minimum character count (inclusive).
        max_length : int
            Maximum character count (inclusive).

        Returns
        -------
        list[dict]
            Filtered list.
        """
        before = len(captions)
        filtered = [
            c
            for c in captions
            if min_length <= len(c.get("text", "")) <= max_length
        ]
        logger.info(
            "Quality filter: {} -> {} captions (min={}, max={})",
            before,
            len(filtered),
            min_length,
            max_length,
        )
        return filtered

    @staticmethod
    def remove_duplicates(captions: list[dict]) -> list[dict]:
        """Remove duplicate captions based on exact text match.

        When duplicates are found the first occurrence is kept.

        Parameters
        ----------
        captions : list[dict]
            Caption dicts (must contain a ``"text"`` key).

        Returns
        -------
        list[dict]
            De-duplicated list preserving original order.
        """
        seen: set[str] = set()
        unique: list[dict] = []
        for cap in captions:
            text = cap.get("text", "")
            if text not in seen:
                seen.add(text)
                unique.append(cap)
        removed = len(captions) - len(unique)
        if removed:
            logger.info("Removed {} duplicate captions.", removed)
        return unique

    # ------------------------------------------------------------------
    # Batch processing
    # ------------------------------------------------------------------

    def process_all(
        self,
        input_dir: str,
        output_path: str,
        min_length: int = 20,
        max_length: int = 500,
    ) -> Path:
        """Read every raw JSON in *input_dir*, clean, filter, and save as JSONL.

        Parameters
        ----------
        input_dir : str
            Directory containing raw JSON files produced by
            :class:`~collector.CaptionCollector`.
        output_path : str
            Destination JSONL file path.
        min_length : int
            Passed to :meth:`filter_quality`.
        max_length : int
            Passed to :meth:`filter_quality`.

        Returns
        -------
        pathlib.Path
            Resolved path of the written JSONL file.
        """
        in_dir = Path(input_dir)
        out_path = Path(output_path)

        json_files = sorted(in_dir.glob("*.json"))
        if not json_files:
            logger.warning("No JSON files found in {}", in_dir)
            return out_path

        logger.info("Processing {} raw JSON file(s) from {}", len(json_files), in_dir)

        all_captions: list[dict] = []
        for jf in json_files:
            with jf.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, list):
                all_captions.extend(data)
            else:
                logger.warning("Unexpected format in {} – skipping.", jf.name)

        logger.info("Loaded {} raw captions total.", len(all_captions))

        # Clean each caption's text in-place
        for cap in all_captions:
            cap["text"] = self.clean_caption(cap.get("text", ""))

        # Filter and deduplicate
        all_captions = self.filter_quality(
            all_captions, min_length=min_length, max_length=max_length
        )
        all_captions = self.remove_duplicates(all_captions)

        # Write JSONL
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as fh:
            for cap in all_captions:
                fh.write(json.dumps(cap, ensure_ascii=False) + "\n")

        logger.info("Saved {} cleaned captions -> {}", len(all_captions), out_path)
        return out_path
