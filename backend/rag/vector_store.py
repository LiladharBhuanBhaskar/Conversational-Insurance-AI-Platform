"""FAISS-backed vector store with safe fallbacks for local MVP execution."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from llama_index.core import Document, StorageContext, VectorStoreIndex, load_index_from_storage
from llama_index.core.embeddings import MockEmbedding

try:
    import faiss
    from llama_index.vector_stores.faiss import FaissVectorStore

    FAISS_AVAILABLE = True
except Exception:
    faiss = None
    FaissVectorStore = None
    FAISS_AVAILABLE = False

logger = logging.getLogger(__name__)


class InsuranceVectorStore:
    def __init__(self, persist_dir: str | Path):
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.faiss_index_path = self.persist_dir / "faiss.index"
        self.embed_model_name = os.getenv("EMBED_MODEL_NAME", "sentence-transformers/all-MiniLM-L6-v2")
        self.embed_model = None
        self.index: VectorStoreIndex | None = None
        self._raw_documents: list[str] = []
        self._load_existing_index()

    def _get_embed_model(self):
        if self.embed_model is not None:
            return self.embed_model

        try:
            from llama_index.embeddings.huggingface import HuggingFaceEmbedding

            self.embed_model = HuggingFaceEmbedding(model_name=self.embed_model_name)
        except Exception as exc:
            logger.warning(
                "Failed to initialize HuggingFace embedding model '%s': %s. "
                "Falling back to MockEmbedding.",
                self.embed_model_name,
                exc,
            )
            self.embed_model = MockEmbedding(embed_dim=384)
        return self.embed_model

    def _embedding_dimension(self) -> int:
        embed_model = self._get_embed_model()
        try:
            return len(embed_model.get_text_embedding("embedding-dimension-check"))
        except Exception:
            return 384

    def _extract_text(self, document) -> str:
        if hasattr(document, "text"):
            return str(document.text)
        return str(document)

    def _store_raw_documents(self, documents: list, replace: bool = False) -> None:
        texts = [self._extract_text(document).strip() for document in documents if self._extract_text(document).strip()]
        if replace:
            self._raw_documents = texts
        else:
            self._raw_documents.extend(texts)

    def _load_existing_index(self) -> None:
        if not FAISS_AVAILABLE or not self.faiss_index_path.exists():
            self.index = None
            return

        try:
            vector_store = FaissVectorStore.from_persist_path(str(self.faiss_index_path))
            storage_context = StorageContext.from_defaults(
                persist_dir=str(self.persist_dir),
                vector_store=vector_store,
            )
            self.index = load_index_from_storage(storage_context, embed_model=self._get_embed_model())
        except Exception as exc:
            logger.warning("Failed to load persisted FAISS index: %s", exc)
            self.index = None

    def _persist_index(self) -> None:
        if self.index is None:
            return
        self.index.storage_context.persist(persist_dir=str(self.persist_dir))
        vector_store = self.index.storage_context.vector_store
        if hasattr(vector_store, "persist"):
            vector_store.persist(str(self.faiss_index_path))

    def build(self, documents: list) -> None:
        if not documents:
            raise ValueError("Cannot build vector store with empty documents list")

        self._store_raw_documents(documents, replace=True)
        if not FAISS_AVAILABLE:
            logger.warning("FAISS is not available. Using lexical retrieval fallback only.")
            self.index = None
            return

        try:
            dimension = self._embedding_dimension()
            faiss_index = faiss.IndexFlatL2(dimension)
            vector_store = FaissVectorStore(faiss_index=faiss_index)
            storage_context = StorageContext.from_defaults(vector_store=vector_store)

            self.index = VectorStoreIndex.from_documents(
                documents=documents,
                storage_context=storage_context,
                embed_model=self._get_embed_model(),
            )
            self._persist_index()
        except Exception as exc:
            logger.warning("FAISS index build failed, using lexical fallback: %s", exc)
            self.index = None

    def upsert(self, documents: list) -> None:
        if not documents:
            return

        if self.index is None:
            # Keep appending to lexical fallback corpus.
            self._store_raw_documents(documents, replace=False)

            # If FAISS is available but index is not initialized, rebuild from all known docs.
            if FAISS_AVAILABLE and self._raw_documents:
                combined_documents = [Document(text=text) for text in self._raw_documents]
                self.build(combined_documents)
            return

        self._store_raw_documents(documents, replace=False)
        try:
            for document in documents:
                self.index.insert(document)
            self._persist_index()
        except Exception as exc:
            logger.warning("FAISS upsert failed, keeping lexical fallback: %s", exc)
            self.index = None

    def _lexical_retrieve(self, query: str, top_k: int) -> list[str]:
        if not self._raw_documents:
            return []

        query_tokens = set(re.findall(r"[a-z0-9]+", query.lower()))
        if not query_tokens:
            return self._raw_documents[:top_k]

        scored: list[tuple[int, str]] = []
        for text in self._raw_documents:
            text_tokens = set(re.findall(r"[a-z0-9]+", text.lower()))
            score = len(query_tokens.intersection(text_tokens))
            if score > 0:
                scored.append((score, text))

        if not scored:
            return self._raw_documents[:top_k]

        scored.sort(key=lambda item: item[0], reverse=True)
        return [text for _, text in scored[:top_k]]

    def retrieve(self, query: str, top_k: int = 3) -> list[str]:
        if self.index is None:
            return self._lexical_retrieve(query=query, top_k=top_k)

        try:
            retriever = self.index.as_retriever(similarity_top_k=top_k)
            nodes = retriever.retrieve(query)

            chunks: list[str] = []
            for node in nodes:
                if hasattr(node, "node") and hasattr(node.node, "get_content"):
                    chunks.append(node.node.get_content())
                elif hasattr(node, "get_content"):
                    chunks.append(node.get_content())
                else:
                    chunks.append(str(node))
            return chunks
        except Exception as exc:
            logger.warning("FAISS retrieval failed, using lexical fallback: %s", exc)
            return self._lexical_retrieve(query=query, top_k=top_k)
