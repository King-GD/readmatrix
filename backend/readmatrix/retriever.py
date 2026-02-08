"""Retriever - semantic search with deduplication, reranking, and context window"""

from typing import Optional

from .config import get_settings
from .models import Chunk
from .indexer import VectorStore, get_embedding_provider


class Retriever:
    """Retrieves relevant chunks for a query"""

    def __init__(self, vectorstore: VectorStore | None = None):
        self.vectorstore = vectorstore or VectorStore()
        self._embedder = None
        self._reranker = None

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
        """
        Search for relevant chunks with reranking and context expansion.

        Args:
            query: Search query
            top_k: Number of results to return
            book_id: Filter by book_id (priority)
            book_title: Filter by book_title (fallback)

        Returns:
            List of relevant Chunks
        """
        settings = get_settings()

        # Generate query embedding
        query_embedding = self.embedder.embed([query])[0]

        # Search with increased k for deduplication and reranking
        fetch_k = top_k * 3 if settings.enable_reranker else top_k * 2
        raw_results = self.vectorstore.search(
            query_embedding=query_embedding,
            top_k=fetch_k,
            book_id=book_id,
            book_title=book_title,
        )

        # 基于距离阈值过滤低相关结果
        if settings.retrieval_max_distance is not None:
            raw_results = [
                chunk
                for chunk in raw_results
                if chunk.distance is None
                or chunk.distance <= settings.retrieval_max_distance
            ]

        # Deduplicate
        deduplicated = self._deduplicate(raw_results)

        # Rerank if enabled
        if settings.enable_reranker and deduplicated:
            deduplicated = self.reranker.rerank(
                query=query,
                chunks=deduplicated,
                top_k=top_k * 2,  # Keep more for context expansion
                model=settings.reranker_model,
            )

        # Take top_k before context expansion
        top_chunks = deduplicated[:top_k]

        # Expand with context window if enabled
        if settings.context_window > 0 and top_chunks:
            top_chunks = self._expand_context(top_chunks, settings.context_window)

        return top_chunks[:top_k]

    def _expand_context(self, chunks: list[Chunk], window: int) -> list[Chunk]:
        """
        Expand chunks by including neighboring chunks from the same document.

        Args:
            chunks: Original chunks
            window: Number of neighbors to include (before and after)

        Returns:
            Expanded list of chunks with context
        """
        if not chunks or window <= 0:
            return chunks

        expanded = []
        seen_ids = set()

        for chunk in chunks:
            # Get neighbors from the same source file
            neighbors = self.vectorstore.get_by_source(
                source_path=chunk.source_path,
                limit=50,  # Get enough to find neighbors
            )

            if not neighbors:
                if chunk.chunk_id not in seen_ids:
                    expanded.append(chunk)
                    seen_ids.add(chunk.chunk_id)
                continue

            # Find current chunk's position
            current_idx = -1
            for i, n in enumerate(neighbors):
                if n.chunk_id == chunk.chunk_id:
                    current_idx = i
                    break

            if current_idx == -1:
                if chunk.chunk_id not in seen_ids:
                    expanded.append(chunk)
                    seen_ids.add(chunk.chunk_id)
                continue

            # Add neighbors within window
            start_idx = max(0, current_idx - window)
            end_idx = min(len(neighbors), current_idx + window + 1)

            for i in range(start_idx, end_idx):
                neighbor = neighbors[i]
                if neighbor.chunk_id not in seen_ids:
                    expanded.append(neighbor)
                    seen_ids.add(neighbor.chunk_id)

        return expanded

    def _deduplicate(self, chunks: list[Chunk]) -> list[Chunk]:
        """
        改进的去重：基于内容去重，允许同章节保留多个不同内容的chunk。
        使用内容前100字符作为去重key，避免完全相同的内容重复出现。
        """
        seen_content = set()
        result = []

        for chunk in chunks:
            # 使用内容的前100字符作为去重key
            content_key = chunk.content[:100] if len(chunk.content) >= 100 else chunk.content

            if content_key not in seen_content:
                seen_content.add(content_key)
                result.append(chunk)

        return result
