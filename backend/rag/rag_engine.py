"""High-level RAG orchestration for insurance knowledge retrieval."""

from __future__ import annotations

import logging
from pathlib import Path
from threading import Lock

from backend.rag.data_loader import load_csv_documents
from backend.rag.vector_store import InsuranceVectorStore

logger = logging.getLogger(__name__)


class RAGEngine:
    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)
        self.persist_dir = self.data_dir / "vector_store"
        self.vector_store = InsuranceVectorStore(self.persist_dir)
        self._lock = Lock()

    def initialize_from_faq(self) -> int:
        faq_path = self.data_dir / "faq.csv"
        if not faq_path.exists():
            logger.warning("FAQ file not found at %s. RAG index will stay empty.", faq_path)
            return 0

        # Build only if no existing index is loaded.
        if self.vector_store.index is not None:
            return 0

        documents = load_csv_documents(faq_path)
        if not documents:
            logger.warning("FAQ file %s is empty or invalid for RAG ingestion.", faq_path)
            return 0

        with self._lock:
            self.vector_store.build(documents)
        return len(documents)

    def rebuild_from_faq(self) -> int:
        faq_path = self.data_dir / "faq.csv"
        documents = load_csv_documents(faq_path)
        if not documents:
            return 0

        with self._lock:
            self.vector_store.build(documents)
        return len(documents)

    def ingest_csv(self, csv_path: str | Path) -> int:
        documents = load_csv_documents(csv_path)
        if not documents:
            return 0

        with self._lock:
            self.vector_store.upsert(documents)
        return len(documents)

    def retrieve(self, query: str, top_k: int = 3) -> list[str]:
        with self._lock:
            return self.vector_store.retrieve(query=query, top_k=top_k)
