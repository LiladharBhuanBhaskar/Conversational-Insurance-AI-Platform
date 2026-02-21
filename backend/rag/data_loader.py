"""Load FAQ and insurance knowledge documents from CSV files."""

from __future__ import annotations

import csv
from pathlib import Path

from llama_index.core import Document


def _iter_csv_rows(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames:
            reader.fieldnames = [
                (field_name or "").replace("\ufeff", "").strip()
                for field_name in reader.fieldnames
            ]

        for row in reader:
            normalized = {}
            for key, value in row.items():
                clean_key = (key or "").replace("\ufeff", "").strip()
                if isinstance(value, str):
                    normalized[clean_key] = value.strip()
                else:
                    normalized[clean_key] = value
            yield normalized


def load_csv_documents(csv_path: str | Path) -> list[Document]:
    path = Path(csv_path)
    if not path.exists():
        return []

    documents: list[Document] = []
    for idx, row in enumerate(_iter_csv_rows(path), start=1):
        question = (row.get("question") or row.get("faq_question") or "").strip()
        answer = (row.get("answer") or row.get("faq_answer") or "").strip()
        category = (row.get("category") or row.get("insurance_type") or "general").strip()

        if question or answer:
            text = (
                f"Insurance Category: {category}\n"
                f"Question: {question}\n"
                f"Answer: {answer}"
            )
        else:
            # Fallback for arbitrary CSV files: preserve all key-value pairs.
            pairs = [f"{key}: {value}" for key, value in row.items() if value]
            text = "\n".join(pairs)

        if not text.strip():
            continue

        documents.append(
            Document(
                text=text,
                metadata={
                    "source": path.name,
                    "row": idx,
                    "category": category,
                },
            )
        )

    return documents
