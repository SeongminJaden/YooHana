"""
HuggingFace Dataset builder for SFT training.

Converts cleaned JSONL caption data into instruction-output formatted
HuggingFace ``Dataset`` / ``DatasetDict`` objects, ready for supervised
fine-tuning.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from datasets import Dataset, DatasetDict, concatenate_datasets

from src.utils.logger import get_logger

logger = get_logger()

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PROCESSED_DIR = _PROJECT_ROOT / "data" / "processed"


class DatasetBuilder:
    """Build HuggingFace Datasets from cleaned caption JSONL files."""

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load_jsonl(jsonl_path: str) -> list[dict[str, Any]]:
        """Read a JSONL file into a list of dicts."""
        path = Path(jsonl_path)
        records: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        logger.info("Loaded {} records from {}", len(records), path)
        return records

    @staticmethod
    def _extract_topic(caption: str) -> str:
        """Derive a short topic hint from the caption text.

        Heuristic: use the first sentence (up to 40 chars) as a rough
        topic descriptor.  This is intentionally simple – a more
        sophisticated approach could leverage an LLM or keyword
        extraction.
        """
        # Take the first sentence-like segment
        for sep in (".", "!", "?", "\n"):
            idx = caption.find(sep)
            if 0 < idx <= 80:
                return caption[:idx].strip()

        # Fallback: first 40 characters
        topic = caption[:40].strip()
        if len(caption) > 40:
            topic += "..."
        return topic

    # ------------------------------------------------------------------
    # Dataset builders
    # ------------------------------------------------------------------

    def build_caption_dataset(
        self,
        jsonl_path: str,
        persona_name: str,
    ) -> Dataset:
        """Build an instruction-output dataset for caption generation SFT.

        Each entry is formatted as:

        * **instruction**: ``"다음 주제에 대한 인스타그램 캡션을 작성해줘: {topic}"``
        * **output**: the actual (cleaned) caption text

        Parameters
        ----------
        jsonl_path : str
            Path to the cleaned JSONL file.
        persona_name : str
            Name of the persona/influencer (stored as metadata in each
            row for multi-persona training).

        Returns
        -------
        datasets.Dataset
        """
        records = self._load_jsonl(jsonl_path)

        instructions: list[str] = []
        outputs: list[str] = []
        personas: list[str] = []
        sources: list[str] = []

        for rec in records:
            # Support both formats:
            #   {"text": "...", "source": "..."}  (from collector/cleaner)
            #   {"instruction": "...", "output": "..."}  (pre-formatted)
            if "instruction" in rec and "output" in rec:
                instruction = rec["instruction"].strip()
                text = rec["output"].strip()
            else:
                text = rec.get("text", "").strip()
                if not text:
                    continue
                topic = self._extract_topic(text)
                instruction = f"다음 주제에 대한 인스타그램 캡션을 작성해줘: {topic}"

            if not text:
                continue

            instructions.append(instruction)
            outputs.append(text)
            personas.append(persona_name)
            sources.append(rec.get("source", ""))

        dataset = Dataset.from_dict(
            {
                "instruction": instructions,
                "output": outputs,
                "persona": personas,
                "source": sources,
            }
        )
        logger.info(
            "Built caption dataset: {} examples for persona '{}'",
            len(dataset),
            persona_name,
        )
        return dataset

    def build_reply_dataset(self, jsonl_path: str) -> Dataset:
        """Build an instruction-output dataset for comment-reply SFT.

        Expected JSONL schema per line::

            {"comment": "...", "reply": "..."}

        * **instruction**: the comment text
        * **output**: the reply text

        Parameters
        ----------
        jsonl_path : str
            Path to the cleaned JSONL file containing comment-reply pairs.

        Returns
        -------
        datasets.Dataset
        """
        records = self._load_jsonl(jsonl_path)

        instructions: list[str] = []
        outputs: list[str] = []

        for rec in records:
            comment = rec.get("comment", "").strip()
            reply = rec.get("reply", "").strip()
            if not comment or not reply:
                continue

            instructions.append(comment)
            outputs.append(reply)

        dataset = Dataset.from_dict(
            {
                "instruction": instructions,
                "output": outputs,
            }
        )
        logger.info("Built reply dataset: {} examples", len(dataset))
        return dataset

    # ------------------------------------------------------------------
    # Merge & split
    # ------------------------------------------------------------------

    @staticmethod
    def merge_datasets(datasets: list[Dataset]) -> Dataset:
        """Concatenate multiple :class:`Dataset` objects into one.

        All datasets must share the same column schema.  Columns that
        exist only in some datasets are filled with ``None``.

        Parameters
        ----------
        datasets : list[Dataset]
            Datasets to merge.

        Returns
        -------
        datasets.Dataset
        """
        if not datasets:
            raise ValueError("Cannot merge an empty list of datasets.")
        if len(datasets) == 1:
            return datasets[0]

        # Align columns: add missing columns with None values
        all_columns: set[str] = set()
        for ds in datasets:
            all_columns.update(ds.column_names)

        aligned: list[Dataset] = []
        for ds in datasets:
            missing = all_columns - set(ds.column_names)
            if missing:
                extras = {col: [None] * len(ds) for col in missing}
                ds = ds.add_column(
                    list(missing)[0], extras[list(missing)[0]]
                ) if len(missing) == 1 else ds
                # For multiple missing columns, add one at a time
                for col in missing:
                    if col not in ds.column_names:
                        ds = ds.add_column(col, [None] * len(ds))
            aligned.append(ds)

        merged = concatenate_datasets(aligned)
        logger.info("Merged {} datasets -> {} total examples", len(datasets), len(merged))
        return merged

    @staticmethod
    def split_train_val(
        dataset: Dataset,
        val_ratio: float = 0.1,
        seed: int = 42,
    ) -> DatasetDict:
        """Split a dataset into train and validation sets.

        Parameters
        ----------
        dataset : Dataset
            The dataset to split.
        val_ratio : float
            Fraction of data to use for validation (0 < val_ratio < 1).
        seed : int
            Random seed for reproducibility.

        Returns
        -------
        datasets.DatasetDict
            A ``DatasetDict`` with ``"train"`` and ``"validation"`` splits.
        """
        if not 0 < val_ratio < 1:
            raise ValueError(f"val_ratio must be in (0, 1), got {val_ratio}")

        split = dataset.train_test_split(test_size=val_ratio, seed=seed)
        result = DatasetDict(
            {
                "train": split["train"],
                "validation": split["test"],
            }
        )
        logger.info(
            "Split dataset: {} train / {} validation",
            len(result["train"]),
            len(result["validation"]),
        )
        return result

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(
        self,
        dataset: Dataset | DatasetDict,
        name: str,
        output_dir: str | Path | None = None,
    ) -> Path:
        """Save a dataset or dataset dict to disk under ``data/processed/``.

        Parameters
        ----------
        dataset : Dataset | DatasetDict
            The dataset to save.
        name : str
            Sub-directory name (e.g. ``"caption_sft"``).
        output_dir : str | Path | None
            Override the default processed-data directory.

        Returns
        -------
        pathlib.Path
            Path where the dataset was saved.
        """
        base = Path(output_dir) if output_dir else _PROCESSED_DIR
        save_path = base / name
        save_path.mkdir(parents=True, exist_ok=True)

        dataset.save_to_disk(str(save_path))
        logger.info("Dataset saved -> {}", save_path)
        return save_path
