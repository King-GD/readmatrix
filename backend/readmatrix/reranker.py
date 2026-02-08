"""Reranker for improving retrieval quality using SiliconFlow API"""

from dataclasses import dataclass
from typing import Optional

from .config import get_settings
from .models import Chunk


@dataclass
class RankedChunk:
    """Chunk with rerank score"""
    chunk: Chunk
    score: float


class Reranker:
    """
    Reranker using SiliconFlow's rerank API.
    Uses Cross-Encoder model to compute query-document relevance scores.
    """

    def __init__(self):
        self._client = None

    @property
    def client(self):
        """Lazy-load HTTP client"""
        if self._client is None:
            import httpx
            settings = get_settings()
            self._client = httpx.Client(
                base_url=settings.siliconflow_base_url.rstrip("/v1"),
                headers={"Authorization": f"Bearer {settings.siliconflow_api_key}"},
                timeout=30.0,
            )
        return self._client

    def rerank(
        self,
        query: str,
        chunks: list[Chunk],
        top_k: Optional[int] = None,
        model: str = "BAAI/bge-reranker-v2-m3",
    ) -> list[Chunk]:
        """
        Rerank chunks based on relevance to query.

        Args:
            query: User's question
            chunks: List of chunks to rerank
            top_k: Number of top results to return (default: all)
            model: Reranker model to use

        Returns:
            Reranked list of chunks (most relevant first)
        """
        if not chunks:
            return []

        settings = get_settings()

        # Skip reranking if API key not configured
        if not settings.siliconflow_api_key:
            return chunks

        try:
            # Prepare documents for reranking
            documents = [chunk.content for chunk in chunks]

            # Call SiliconFlow rerank API
            response = self.client.post(
                "/v1/rerank",
                json={
                    "model": model,
                    "query": query,
                    "documents": documents,
                    "top_n": top_k or len(chunks),
                    "return_documents": False,
                },
            )
            response.raise_for_status()
            result = response.json()

            # Sort chunks by rerank score
            ranked_indices = result.get("results", [])
            reranked_chunks = []

            for item in ranked_indices:
                idx = item.get("index", 0)
                if 0 <= idx < len(chunks):
                    reranked_chunks.append(chunks[idx])

            return reranked_chunks[:top_k] if top_k else reranked_chunks

        except Exception as e:
            # If reranking fails, return original order
            print(f"Reranker error: {e}")
            return chunks[:top_k] if top_k else chunks
