"""Index manager - orchestrates scanning, parsing, chunking, and indexing"""

from pathlib import Path
from datetime import datetime
from typing import Callable, Optional

from ..config import get_settings
from ..models import Chunk, FileRecord
from ..vault import (
    scan_vault,
    parse_markdown,
    chunk_weread_document,
    get_files_needing_update,
    compute_file_hash,
)
from .database import Database
from .vectorstore import VectorStore
from .embedder import get_embedding_provider


class IndexManager:
    """Manages the indexing pipeline"""
    
    def __init__(
        self,
        db: Database | None = None,
        vectorstore: VectorStore | None = None,
    ):
        self.db = db or Database()
        self.vectorstore = vectorstore or VectorStore()
        self._embedder = None
    
    @property
    def embedder(self):
        if self._embedder is None:
            self._embedder = get_embedding_provider()
        return self._embedder
    
    def full_rebuild(
        self,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> dict:
        """
        Perform full index rebuild.
        
        Args:
            progress_callback: Optional callback(current, total, message)
        
        Returns:
            Statistics dict
        """
        settings = get_settings()
        
        try:
            # Clear existing data
            self.vectorstore.clear()
        except Exception as e:
            print(f"ERROR clearing vectorstore: {e}")
            raise
        
        try:
            # Scan vault
            files = list(scan_vault())
        except Exception as e:
            print(f"ERROR scanning vault: {e}")
            raise
            
        total = len(files)
        
        if progress_callback:
            progress_callback(0, total, "Scanning vault...")
        
        stats = {
            "total_files": total,
            "indexed_files": 0,
            "total_chunks": 0,
            "errors": [],
        }
        
        for i, (file_path, source_type) in enumerate(files):
            try:
                chunks = self._index_file(file_path, source_type)
                stats["indexed_files"] += 1
                stats["total_chunks"] += len(chunks)
                
                if progress_callback:
                    progress_callback(i + 1, total, f"Indexed: {file_path.name}")
                    
            except Exception as e:
                error_msg = f"{file_path}: {str(e)}"
                stats["errors"].append(error_msg)
                
                # Record error in database
                record = FileRecord(
                    path=str(file_path),
                    hash="",
                    mtime=0,
                    status="error",
                    source_type=source_type,
                    book_id=None,
                    last_error=str(e),
                )
                self.db.upsert_file_record(record)
        
        return stats
    
    def incremental_update(
        self,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> dict:
        """
        Perform incremental update - only index changed files.
        
        Returns:
            Statistics dict
        """
        # Get current index state
        indexed_records = self.db.get_all_file_records()
        
        # Scan vault
        scanned_files = list(scan_vault())
        
        # Determine what needs updating
        files_to_index, paths_to_remove = get_files_needing_update(
            scanned_files, indexed_records
        )
        
        total = len(files_to_index) + len(paths_to_remove)
        
        stats = {
            "files_to_index": len(files_to_index),
            "files_to_remove": len(paths_to_remove),
            "indexed": 0,
            "removed": 0,
            "total_chunks": 0,
            "errors": [],
        }
        
        if progress_callback:
            progress_callback(0, total, "Starting incremental update...")
        
        # Remove deleted files
        for i, path in enumerate(paths_to_remove):
            self.vectorstore.delete_by_source_path(path)
            self.db.delete_file_record(path)
            stats["removed"] += 1
            
            if progress_callback:
                progress_callback(i + 1, total, f"Removed: {Path(path).name}")
        
        # Index new/changed files
        offset = len(paths_to_remove)
        for i, (file_path, source_type) in enumerate(files_to_index):
            try:
                # Delete old chunks first
                self.vectorstore.delete_by_source_path(str(file_path))
                
                chunks = self._index_file(file_path, source_type)
                stats["indexed"] += 1
                stats["total_chunks"] += len(chunks)
                
                if progress_callback:
                    progress_callback(offset + i + 1, total, f"Indexed: {file_path.name}")
                    
            except Exception as e:
                error_msg = f"{file_path}: {str(e)}"
                stats["errors"].append(error_msg)
                self.db.update_file_status(str(file_path), "error", str(e))
        
        return stats
    
    def _index_file(self, file_path: Path, source_type: str) -> list[Chunk]:
        """Index a single file"""
        # Parse file
        document = parse_markdown(file_path, source_type)
        
        # Chunk based on source type
        if source_type == "weread":
            chunks = chunk_weread_document(document)
        else:
            # For now, treat entire file as one chunk
            # TODO: Implement generic markdown chunker
            from ..vault.chunker import make_chunk_id
            chunks = [Chunk(
                chunk_id=make_chunk_id(str(file_path), "main"),
                block_id="main",
                content=document.content[:2000],  # Limit size
                source_path=str(file_path),
                title_path=[document.title],
                book_id="",
                book_title=document.title,
                author=None,
                highlight_time=None,
            )]
        
        if chunks:
            # Generate embeddings
            texts = [c.content for c in chunks]
            embeddings = self.embedder.embed(texts)
            
            # Store in vector database
            self.vectorstore.add_chunks(chunks, embeddings)
        
        # Update file record
        record = FileRecord(
            path=str(file_path),
            hash=document.hash,
            mtime=document.mtime,
            status="indexed",
            source_type=source_type,
            book_id=document.book_id,
            last_error=None,
        )
        self.db.upsert_file_record(record)
        
        return chunks
    
    def get_stats(self) -> dict:
        """Get current index statistics"""
        file_counts = self.db.get_file_count()
        chunk_count = self.vectorstore.get_chunk_count()
        
        return {
            "files": file_counts,
            "total_files": sum(file_counts.values()),
            "total_chunks": chunk_count,
            "book_ids": self.db.get_book_ids(),
        }
