"""Retriever - dense or hybrid search with reranking and context window."""

from __future__ import annotations

from typing import Optional

from .config import get_settings
from .models import Chunk
from .indexer import Database, VectorStore, get_embedding_provider
from .retrieval_fusion import reciprocal_rank_fusion


class Retriever:
    """Retrieves relevant chunks for a query."""

    def __init__(
        self,
        vectorstore: VectorStore | None = None,
        db: Database | None = None,
        embedder=None,
        reranker=None,
    ):
        self.vectorstore = vectorstore or VectorStore()
        self.db = db or Database()
        self._embedder = embedder
        self._reranker = reranker

    @property
    def embedder(self):
        if self._embedder is None:
            self._embedder = get_embedding_provider()
        return self._embedder

    @property
    def reranker(self):
        if self._reranker is None:
            from .reranker import Reranker

            self._reranker = Reranker()
        return self._reranker

    def search(
        self,
        query: str,
        top_k: int = 5,
        book_id: Optional[str] = None,
        book_title: Optional[str] = None,
    ) -> list[Chunk]:
        """Search for relevant chunks with optional hybrid recall."""
        settings = get_settings()
        retrieval_mode = getattr(settings, "retrieval_mode", "dense")

        dense_results = self._search_dense(
            query=query,
            top_k=top_k,
            book_id=book_id,
            book_title=book_title,
        )

        candidates = dense_results
        if retrieval_mode == "hybrid" and getattr(settings, "enable_sparse_retrieval", True):
            candidates = self._hybrid_candidates(
                query=query,
                dense_results=dense_results,
                top_k=top_k,
                book_id=book_id,
                book_title=book_title,
            )

        return self._apply_rerank_and_context(
            query=query,
            chunks=candidates,
            top_k=top_k,
        )

    def _search_dense(
        self,
        query: str,
        top_k: int,
        book_id: Optional[str] = None,
        book_title: Optional[str] = None,
    ) -> list[Chunk]:
        """Search the dense vector index."""
        settings = get_settings()
        query_embedding = self.embedder.embed([query])[0]

        dense_top_k = max(top_k, getattr(settings, "dense_top_k", top_k))
        fetch_k = max(
            dense_top_k,
            top_k * 3 if settings.enable_reranker else top_k * 2,
        )
        raw_results = self.vectorstore.search(
            query_embedding=query_embedding,
            top_k=fetch_k,
            book_id=book_id,
            book_title=book_title,
        )

        if settings.retrieval_max_distance is not None:
            raw_results = [
                chunk
                for chunk in raw_results
                if chunk.distance is None
                or chunk.distance <= settings.retrieval_max_distance
            ]

        return raw_results

    def _hybrid_candidates(
        self,
        query: str,
        dense_results: list[Chunk],
        top_k: int,
        book_id: Optional[str] = None,
        book_title: Optional[str] = None,
    ) -> list[Chunk]:
        """Fuse dense and sparse candidates via RRF."""
        settings = get_settings()
        sparse_top_k = max(top_k * 2, getattr(settings, "sparse_top_k", top_k))
        fusion_top_k = max(top_k * 2, getattr(settings, "fusion_top_k", top_k))

        try:
            sparse_results = self.db.search_sparse_chunks(
                query=query,
                limit=sparse_top_k,
                book_id=book_id,
                book_title=book_title,
            )
        except Exception as exc:
            print(f"Sparse retrieval error: {exc}")
            sparse_results = []

        return reciprocal_rank_fusion(
            [dense_results, sparse_results],
            top_k=fusion_top_k,
        )

    def _apply_rerank_and_context(
        self,
        query: str,
        chunks: list[Chunk],
        top_k: int,
    ) -> list[Chunk]:
        """Apply dedupe, rerank, and context window expansion."""
        settings = get_settings()
        deduplicated = self._deduplicate(chunks)

        if settings.enable_reranker and deduplicated:
            deduplicated = self.reranker.rerank(
                query=query,
                chunks=deduplicated,
                top_k=top_k * 2,
                model=settings.reranker_model,
            )

        top_chunks = deduplicated[:top_k]

        if settings.context_window > 0 and top_chunks:
            top_chunks = self._expand_context(top_chunks, settings.context_window)

        return top_chunks[:top_k]

    def _expand_context(self, chunks: list[Chunk], window: int) -> list[Chunk]:
        """Expand chunks by including neighboring chunks from the same document."""
        if not chunks or window <= 0:
            return chunks

        expanded = []
        seen_ids = set()

        for chunk in chunks:
            neighbors = self.vectorstore.get_by_source(
                source_path=chunk.source_path,
                limit=50,
            )

            if not neighbors:
                if chunk.chunk_id not in seen_ids:
                    expanded.append(chunk)
                    seen_ids.add(chunk.chunk_id)
                continue

            current_idx = -1
            for i, neighbor in enumerate(neighbors):
                if neighbor.chunk_id == chunk.chunk_id:
                    current_idx = i
                    break

            if current_idx == -1:
                if chunk.chunk_id not in seen_ids:
                    expanded.append(chunk)
                    seen_ids.add(chunk.chunk_id)
                continue

            start_idx = max(0, current_idx - window)
            end_idx = min(len(neighbors), current_idx + window + 1)

            for i in range(start_idx, end_idx):
                neighbor = neighbors[i]
                if neighbor.chunk_id not in seen_ids:
                    expanded.append(neighbor)
                    seen_ids.add(neighbor.chunk_id)

        return expanded

    def _deduplicate(self, chunks: list[Chunk]) -> list[Chunk]:
        """Deduplicate chunks by a short content prefix."""
        seen_content = set()
        result = []

        for chunk in chunks:
            content_key = chunk.content[:100] if len(chunk.content) >= 100 else chunk.content

            if content_key not in seen_content:
                seen_content.add(content_key)
                result.append(chunk)

        return result
