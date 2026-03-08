"""Daily review service for spaced repetition style recall."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Callable

from .conversation import ConversationService
from .indexer import Database, VectorStore
from .models import Citation, Chunk, ReviewItem


@dataclass
class DailyReviewResult:
    """Result returned after generating or reusing the daily review conversation."""

    conversation_id: str
    title: str
    status: str
    selected_chunk_id: str | None = None


class ReviewService:
    """Generate one daily review conversation from due local notes."""

    def __init__(
        self,
        db: Database | None = None,
        vectorstore: VectorStore | None = None,
        conversation_service: ConversationService | None = None,
        now_provider: Callable[[], datetime] | None = None,
        review_schedule_days: list[int] | None = None,
    ):
        self.db = db or Database()
        self.vectorstore = vectorstore or VectorStore()
        self.conversation_service = conversation_service or ConversationService(db=self.db)
        self.now_provider = now_provider or datetime.now
        self.review_schedule_days = review_schedule_days or [1, 3, 7, 14, 30]

    def generate_daily_review(self, target_date: date | None = None) -> DailyReviewResult:
        """Create or reuse the daily review conversation for a date."""
        current_time = self.now_provider()
        review_date = target_date or current_time.date()
        title = f"今日回顾 {review_date.isoformat()}"

        existing = self.db.get_conversation_by_title(title)
        if existing:
            return DailyReviewResult(
                conversation_id=existing["id"],
                title=title,
                status="existing",
            )

        self.ensure_review_items()
        selected = self._select_due_chunk(review_date=review_date, current_time=current_time)

        conversation_id = self.conversation_service.create_conversation(title=title)
        if selected is None:
            self.conversation_service.append_assistant_message(
                conversation_id,
                self._build_empty_message(review_date),
                citations=[],
            )
            return DailyReviewResult(
                conversation_id=conversation_id,
                title=title,
                status="empty",
            )

        item, chunk = selected
        citation = Citation.from_chunk(chunk, 1)
        self.conversation_service.append_assistant_message(
            conversation_id,
            self._build_review_message(item, chunk, review_date),
            citations=[citation.to_dict()],
        )
        self.db.mark_review_item_reviewed(
            chunk_id=item.chunk_id,
            reviewed_at=current_time,
            next_review_at=self._next_due_time(current_time, item.review_count + 1),
        )
        return DailyReviewResult(
            conversation_id=conversation_id,
            title=title,
            status="ready",
            selected_chunk_id=item.chunk_id,
        )

    def ensure_review_items(self):
        """Backfill review rows for indexed chunks that do not have schedules yet."""
        chunks = self.vectorstore.list_chunks()
        if not chunks:
            return

        file_records = {
            record.path: record
            for record in self.db.list_file_records()
        }
        now = self.now_provider()

        for chunk in chunks:
            if self.db.get_review_item(chunk.chunk_id):
                continue

            file_record = file_records.get(chunk.source_path)
            first_seen_at = file_record.updated_at if file_record else now
            content_type = file_record.source_type if file_record else "markdown"
            created_at = now
            self.db.create_review_item(
                ReviewItem(
                    chunk_id=chunk.chunk_id,
                    source_path=chunk.source_path,
                    content_type=content_type,
                    first_seen_at=first_seen_at,
                    last_reviewed_at=None,
                    review_count=0,
                    next_review_at=self._next_due_time(first_seen_at, 0),
                    status="active",
                    created_at=created_at,
                    updated_at=created_at,
                )
            )

    def _select_due_chunk(
        self,
        review_date: date,
        current_time: datetime,
    ) -> tuple[ReviewItem, Chunk] | None:
        """Select the one most relevant chunk to review today."""
        due_before = datetime.combine(review_date, time.max)
        due_items = self.db.list_due_review_items(due_before=due_before, limit=50)

        ranked: list[tuple[ReviewItem, Chunk]] = []
        for item in due_items:
            chunk = self.vectorstore.get_chunk(item.chunk_id)
            if chunk is None:
                self.db.archive_review_item(item.chunk_id)
                continue
            ranked.append((item, chunk))

        if not ranked:
            return None

        ranked.sort(
            key=lambda pair: (
                pair[0].next_review_at,
                -pair[0].review_count,
                -len(pair[1].content.strip()),
            )
        )
        return ranked[0]

    def _next_due_time(self, base_time: datetime, completed_reviews: int) -> datetime:
        """Calculate the next due time after N completed reviews."""
        interval_index = min(completed_reviews, len(self.review_schedule_days) - 1)
        interval_days = self.review_schedule_days[interval_index]
        return base_time + timedelta(days=interval_days)

    def _build_review_message(
        self,
        item: ReviewItem,
        chunk: Chunk,
        review_date: date,
    ) -> str:
        """Build the markdown content for the daily review message."""
        stage_number = min(item.review_count + 1, len(self.review_schedule_days))
        interval_days = self.review_schedule_days[min(item.review_count, len(self.review_schedule_days) - 1)]
        chapter = " / ".join([part for part in chunk.title_path if part])
        chapter_line = f"- 位置：{chapter}" if chapter else "- 位置：未标注章节"

        return "\n".join(
            [
                f"# 今日回顾 {review_date.isoformat()}",
                "",
                f"今天建议你重读这段内容。[1]",
                "",
                f"- 书名：{chunk.book_title or '未命名内容'}",
                chapter_line,
                f"- 回顾原因：距离进入复习系统已满 {interval_days} 天，这是第 {stage_number} 次回顾",
                "",
                "## 原文片段",
                "",
                f"> {chunk.content.strip().replace(chr(10), chr(10) + '> ')}",
                "",
                "如果你想继续展开，可以直接在这个会话里追问。",
            ]
        )

    def _build_empty_message(self, review_date: date) -> str:
        """Build the empty-state message when nothing is due."""
        return "\n".join(
            [
                f"# 今日回顾 {review_date.isoformat()}",
                "",
                "今天没有到期的回顾内容。",
                "",
                "你可以明天再来生成新的回顾，或者继续正常提问。",
            ]
        )
