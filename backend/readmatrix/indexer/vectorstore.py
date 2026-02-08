"""ChromaDB vector store for chunks"""

import chromadb
from pathlib import Path
from typing import Optional

from ..config import get_settings
from ..models import Chunk


class VectorStore:
    """ChromaDB vector store manager"""
    
    COLLECTION_NAME = "readmatrix_chunks"
    
    def __init__(self, persist_path: Path | None = None):
        settings = get_settings()
        self.persist_path = persist_path or settings.chroma_path
        self.persist_path.mkdir(parents=True, exist_ok=True)
        
        settings = chromadb.config.Settings(
            chroma_api_impl="chromadb.api.segment.SegmentAPI"
        )
        self.client = chromadb.PersistentClient(
            path=str(self.persist_path),
            settings=settings,
        )
        self.collection = self.client.get_or_create_collection(
            name=self.COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"}
        )
    
    def add_chunks(self, chunks: list[Chunk], embeddings: list[list[float]]):
        """Add chunks with their embeddings to the store"""
        if not chunks:
            return
        
        self.collection.upsert(
            ids=[c.chunk_id for c in chunks],
            documents=[c.content for c in chunks],
            embeddings=embeddings,
            metadatas=[c.to_metadata() for c in chunks],
        )
    
    def delete_by_source_path(self, source_path: str):
        """Delete all chunks from a specific source file"""
        # ChromaDB requires getting IDs first
        results = self.collection.get(
            where={"source_path": source_path},
            include=[]
        )
        if results["ids"]:
            self.collection.delete(ids=results["ids"])
    
    def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        book_id: Optional[str] = None,
        book_title: Optional[str] = None,
    ) -> list[Chunk]:
        """
        Search for similar chunks.
        
        Args:
            query_embedding: Query vector
            top_k: Number of results
            book_id: Filter by book_id (priority)
            book_title: Filter by book_title (fallback)
        
        Returns:
            List of matching Chunks
        """
        # Build filter
        where = None
        if book_id:
            where = {"book_id": book_id}
        elif book_title:
            where = {"book_title": {"$contains": book_title}}
        
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        
        chunks = []
        ids = results.get("ids", [])
        if ids and ids[0]:
            distances = results.get("distances", [[]])[0]
            for i, chunk_id in enumerate(ids[0]):
                chunk = Chunk.from_metadata(
                    chunk_id=chunk_id,
                    content=results["documents"][0][i],
                    metadata=results["metadatas"][0][i],
                    distance=distances[i] if i < len(distances) else None,
                )
                chunks.append(chunk)
        
        return chunks
    
    def get_chunk_count(self) -> int:
        """Get total number of chunks"""
        return self.collection.count()
    
    def get_all_book_ids(self) -> list[str]:
        """Get all unique book IDs in the store"""
        # This is a workaround since ChromaDB doesn't have DISTINCT
        results = self.collection.get(include=["metadatas"])
        book_ids = set()
        for metadata in results.get("metadatas", []):
            if metadata and metadata.get("book_id"):
                book_ids.add(metadata["book_id"])
        return list(book_ids)
    
    def test_persistence(self) -> bool:
        """Test if the store can persist data (for doctor check)"""
        try:
            test_collection = self.client.get_or_create_collection("_test_persistence")
            test_collection.add(
                ids=["test"],
                documents=["test"],
                embeddings=[[0.0] * 384],  # Minimal embedding
            )
            self.client.delete_collection("_test_persistence")
            return True
        except Exception:
            return False
    
    def clear(self):
        """Clear all data (for full rebuild)"""
        self.client.delete_collection(self.COLLECTION_NAME)
        self.collection = self.client.get_or_create_collection(
            name=self.COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"}
        )

    def get_by_source(self, source_path: str, limit: int = 50) -> list[Chunk]:
        """
        Get all chunks from a specific source file, ordered by position.
        Used for context window expansion.

        Args:
            source_path: Path to source file
            limit: Maximum chunks to return

        Returns:
            List of chunks from the source file
        """
        results = self.collection.get(
            where={"source_path": source_path},
            include=["documents", "metadatas"],
            limit=limit,
        )

        chunks = []
        ids = results.get("ids", [])
        documents = results.get("documents", [])
        metadatas = results.get("metadatas", [])

        for i, chunk_id in enumerate(ids):
            chunk = Chunk.from_metadata(
                chunk_id=chunk_id,
                content=documents[i] if i < len(documents) else "",
                metadata=metadatas[i] if i < len(metadatas) else {},
            )
            chunks.append(chunk)

        # Sort by block_id to maintain document order
        chunks.sort(key=lambda c: c.block_id or "")

        return chunks
