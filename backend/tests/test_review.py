"""Tests for daily review generation and scheduling."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from readmatrix.conversation import ConversationService
from readmatrix.indexer.database import Database
from readmatrix.models import Chunk, FileRecord
from readmatrix.review import ReviewService


@dataclass
class FakeVectorStore:
    """Minimal vector store for review service tests."""

    chunks: list[Chunk]

    def list_chunks(self) -> list[Chunk]:
        return self.chunks

    def get_chunk(self, chunk_id: str) -> Chunk | None:
        for chunk in self.chunks:
            if chunk.chunk_id == chunk_id:
                return chunk
        return None


def make_chunk(
    chunk_id: str,
    source_path: str,
    content: str,
    book_title: str = "测试书籍",
    block_id: str = "block-1",
) -> Chunk:
    """Create a test chunk."""
    return Chunk(
        chunk_id=chunk_id,
        block_id=block_id,
        content=content,
        source_path=source_path,
        title_path=["第一章"],
        book_id=f"book-{chunk_id}",
        book_title=book_title,
        author="作者",
        highlight_time=None,
    )


def insert_file_record(
    db: Database,
    source_path: str,
    updated_at: datetime,
):
    """Insert one indexed file record so review initialization can backfill timestamps."""
    db.upsert_file_record(
        FileRecord(
            path=source_path,
            hash="hash",
            mtime=updated_at.timestamp(),
            status="indexed",
            source_type="weread",
            book_id="book-id",
            last_error=None,
            updated_at=updated_at,
        )
    )


def test_generate_daily_review_reuses_same_day_conversation(tmp_path: Path):
    """Generating twice on the same day should reuse the same conversation."""
    now = datetime(2026, 3, 8, 9, 0, 0)
    chunk = make_chunk(
        chunk_id="chunk-1",
        source_path="E:/vault/book-1.md",
        content="值得回顾的一段内容",
    )
    db = Database(db_path=tmp_path / "review.db")
    insert_file_record(db, chunk.source_path, now - timedelta(days=2))

    service = ReviewService(
        db=db,
        vectorstore=FakeVectorStore([chunk]),
        conversation_service=ConversationService(db=db),
        now_provider=lambda: now,
    )

    first = service.generate_daily_review()
    second = service.generate_daily_review()

    assert first.status == "ready"
    assert second.status == "existing"
    assert first.conversation_id == second.conversation_id


def test_generate_daily_review_marks_only_one_due_item(tmp_path: Path):
    """Only one due item should be chosen and advanced each day."""
    now = datetime(2026, 3, 8, 9, 0, 0)
    first_chunk = make_chunk(
        chunk_id="chunk-1",
        source_path="E:/vault/book-1.md",
        content="较长较长较长的第一条回顾内容",
        block_id="block-a",
    )
    second_chunk = make_chunk(
        chunk_id="chunk-2",
        source_path="E:/vault/book-2.md",
        content="第二条回顾内容",
        block_id="block-b",
    )
    db = Database(db_path=tmp_path / "review.db")
    insert_file_record(db, first_chunk.source_path, now - timedelta(days=5))
    insert_file_record(db, second_chunk.source_path, now - timedelta(days=2))

    service = ReviewService(
        db=db,
        vectorstore=FakeVectorStore([first_chunk, second_chunk]),
        conversation_service=ConversationService(db=db),
        now_provider=lambda: now,
    )

    result = service.generate_daily_review()

    assert result.status == "ready"
    first_item = db.get_review_item(first_chunk.chunk_id)
    second_item = db.get_review_item(second_chunk.chunk_id)
    assert first_item is not None
    assert second_item is not None
    assert first_item.review_count == 1
    assert second_item.review_count == 0


def test_generate_daily_review_returns_empty_when_nothing_due(tmp_path: Path):
    """If no content is due, create an empty-state daily review conversation."""
    now = datetime(2026, 3, 8, 9, 0, 0)
    recent_chunk = make_chunk(
        chunk_id="chunk-1",
        source_path="E:/vault/book-1.md",
        content="刚刚加入复习系统的内容",
    )
    db = Database(db_path=tmp_path / "review.db")
    insert_file_record(db, recent_chunk.source_path, now)

    service = ReviewService(
        db=db,
        vectorstore=FakeVectorStore([recent_chunk]),
        conversation_service=ConversationService(db=db),
        now_provider=lambda: now,
    )

    result = service.generate_daily_review()
    messages = ConversationService(db=db).list_messages(result.conversation_id, limit=10)

    assert result.status == "empty"
    assert len(messages) == 1
    assert "今天没有到期的回顾内容" in messages[0].content
