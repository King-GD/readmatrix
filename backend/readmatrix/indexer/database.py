"""SQLite database for file index state and conversation management"""

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from ..config import get_settings
from ..models import FileRecord


CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS files (
    path TEXT PRIMARY KEY,
    hash TEXT NOT NULL,
    mtime REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    source_type TEXT NOT NULL DEFAULT 'markdown',
    book_id TEXT,
    last_error TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    progress INTEGER DEFAULT 0,
    total INTEGER DEFAULT 0,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    title TEXT,
    status TEXT NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS conversation_messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    citations_json TEXT,
    created_at TEXT NOT NULL,
    token_estimate INTEGER NOT NULL DEFAULT 0,
    is_clarification INTEGER NOT NULL DEFAULT 0,
    is_summary INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_files_status ON files(status);
CREATE INDEX IF NOT EXISTS idx_files_book_id ON files(book_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_conv_updated_at ON conversations(updated_at);
CREATE INDEX IF NOT EXISTS idx_msg_conversation_created_at ON conversation_messages(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_msg_conversation_summary ON conversation_messages(conversation_id, is_summary);
"""


class Database:
    """SQLite database manager for file index state and conversations"""

    def __init__(self, db_path: Path | None = None):
        settings = get_settings()
        self.db_path = db_path or settings.sqlite_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Initialize database tables"""
        with self.connection() as conn:
            conn.executescript(CREATE_TABLES_SQL)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """Get database connection with auto-commit"""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # === File Records ===

    def get_all_file_records(self) -> dict[str, tuple[str, float]]:
        """Get all indexed file records as path -> (hash, mtime)"""
        with self.connection() as conn:
            rows = conn.execute("SELECT path, hash, mtime FROM files").fetchall()
            return {row["path"]: (row["hash"], row["mtime"]) for row in rows}

    def get_file_record(self, path: str) -> FileRecord | None:
        """Get a single file record"""
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM files WHERE path = ?", (path,)
            ).fetchone()
            if row:
                return FileRecord(
                    path=row["path"],
                    hash=row["hash"],
                    mtime=row["mtime"],
                    status=row["status"],
                    source_type=row["source_type"],
                    book_id=row["book_id"],
                    last_error=row["last_error"],
                    updated_at=datetime.fromisoformat(row["updated_at"]),
                )
            return None

    def upsert_file_record(self, record: FileRecord):
        """Insert or update a file record"""
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO files (path, hash, mtime, status, source_type, book_id, last_error, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    hash = excluded.hash,
                    mtime = excluded.mtime,
                    status = excluded.status,
                    source_type = excluded.source_type,
                    book_id = excluded.book_id,
                    last_error = excluded.last_error,
                    updated_at = excluded.updated_at
                """,
                (
                    record.path,
                    record.hash,
                    record.mtime,
                    record.status,
                    record.source_type,
                    record.book_id,
                    record.last_error,
                    record.updated_at.isoformat(),
                ),
            )

    def delete_file_record(self, path: str):
        """Delete a file record"""
        with self.connection() as conn:
            conn.execute("DELETE FROM files WHERE path = ?", (path,))

    def update_file_status(self, path: str, status: str, error: str | None = None):
        """Update file status and optionally error"""
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE files SET status = ?, last_error = ?, updated_at = ?
                WHERE path = ?
                """,
                (status, error, datetime.now().isoformat(), path),
            )

    def get_file_count(self) -> dict[str, int]:
        """Get file count by status"""
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) as count FROM files GROUP BY status"
            ).fetchall()
            return {row["status"]: row["count"] for row in rows}

    def get_book_ids(self) -> list[str]:
        """Get all unique book IDs"""
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT DISTINCT book_id FROM files WHERE book_id IS NOT NULL"
            ).fetchall()
            return [row["book_id"] for row in rows]

    # === Tasks ===

    def create_task(self, task_type: str, total: int = 0) -> int:
        """Create a new task and return its ID"""
        now = datetime.now().isoformat()
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO tasks (type, status, progress, total, created_at, updated_at)
                VALUES (?, 'running', 0, ?, ?, ?)
                """,
                (task_type, total, now, now),
            )
            return cursor.lastrowid

    def update_task_progress(self, task_id: int, progress: int):
        """Update task progress"""
        with self.connection() as conn:
            conn.execute(
                "UPDATE tasks SET progress = ?, updated_at = ? WHERE id = ?",
                (progress, datetime.now().isoformat(), task_id),
            )

    def complete_task(self, task_id: int, status: str = "done", error: str | None = None):
        """Mark task as complete"""
        with self.connection() as conn:
            conn.execute(
                "UPDATE tasks SET status = ?, error = ?, updated_at = ? WHERE id = ?",
                (status, error, datetime.now().isoformat(), task_id),
            )

    def get_latest_task(self, task_type: str | None = None) -> dict | None:
        """Get the latest task"""
        with self.connection() as conn:
            if task_type:
                row = conn.execute(
                    "SELECT * FROM tasks WHERE type = ? ORDER BY id DESC LIMIT 1",
                    (task_type,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM tasks ORDER BY id DESC LIMIT 1"
                ).fetchone()
            return dict(row) if row else None

    # === Conversations ===

    def create_conversation(
        self,
        title: str | None = None,
        status: str = "active",
        conversation_id: str | None = None,
    ) -> str:
        """创建会话并返回会话 ID。"""
        now = datetime.now().isoformat()
        conv_id = conversation_id or uuid.uuid4().hex
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO conversations (id, created_at, updated_at, title, status)
                VALUES (?, ?, ?, ?, ?)
                """,
                (conv_id, now, now, title, status),
            )
        return conv_id

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        """按会话 ID 查询会话信息。"""
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
            return dict(row) if row else None

    def conversation_exists(self, conversation_id: str) -> bool:
        """判断会话是否存在。"""
        return self.get_conversation(conversation_id) is not None

    def touch_conversation(self, conversation_id: str):
        """更新会话更新时间。"""
        with self.connection() as conn:
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (datetime.now().isoformat(), conversation_id),
            )

    def delete_conversation(self, conversation_id: str):
        """删除会话及其所有消息。"""
        with self.connection() as conn:
            conn.execute(
                "DELETE FROM conversations WHERE id = ?",
                (conversation_id,),
            )

    def add_conversation_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        citations: list[dict] | None = None,
        token_estimate: int = 0,
        is_clarification: bool = False,
        is_summary: bool = False,
        message_id: str | None = None,
    ) -> str:
        """写入一条会话消息并返回消息 ID。"""
        msg_id = message_id or uuid.uuid4().hex
        created_at = datetime.now().isoformat()
        citations_json = json.dumps(citations or [], ensure_ascii=False)

        with self.connection() as conn:
            if is_summary:
                conn.execute(
                    "DELETE FROM conversation_messages WHERE conversation_id = ? AND is_summary = 1",
                    (conversation_id,),
                )
            conn.execute(
                """
                INSERT INTO conversation_messages (
                    id,
                    conversation_id,
                    role,
                    content,
                    citations_json,
                    created_at,
                    token_estimate,
                    is_clarification,
                    is_summary
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    msg_id,
                    conversation_id,
                    role,
                    content,
                    citations_json,
                    created_at,
                    token_estimate,
                    int(is_clarification),
                    int(is_summary),
                ),
            )
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (created_at, conversation_id),
            )

        return msg_id

    def _to_message_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        """将数据库行转换为会话消息字典。"""
        citations = []
        citations_json = row["citations_json"]
        if citations_json:
            try:
                citations = json.loads(citations_json)
            except json.JSONDecodeError:
                citations = []
        return {
            "id": row["id"],
            "conversation_id": row["conversation_id"],
            "role": row["role"],
            "content": row["content"],
            "citations": citations,
            "created_at": row["created_at"],
            "token_estimate": row["token_estimate"],
            "is_clarification": bool(row["is_clarification"]),
            "is_summary": bool(row["is_summary"]),
        }

    def list_conversation_messages(
        self,
        conversation_id: str,
        limit: int = 30,
        offset: int = 0,
        include_system: bool = True,
    ) -> list[dict[str, Any]]:
        """分页读取会话消息，按时间升序返回。"""
        system_filter = "" if include_system else " AND role != 'system'"
        with self.connection() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM conversation_messages
                WHERE conversation_id = ? {system_filter}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (conversation_id, limit, offset),
            ).fetchall()
        rows = list(reversed(rows))
        return [self._to_message_dict(row) for row in rows]

    def get_recent_conversation_messages(
        self,
        conversation_id: str,
        limit: int = 12,
        include_system: bool = False,
    ) -> list[dict[str, Any]]:
        """读取最近 N 条消息，按时间升序返回。"""
        return self.list_conversation_messages(
            conversation_id=conversation_id,
            limit=limit,
            offset=0,
            include_system=include_system,
        )

    def count_conversation_messages(
        self,
        conversation_id: str,
        include_system: bool = False,
        role: str | None = None,
    ) -> int:
        """统计会话消息数量。"""
        where_clauses = ["conversation_id = ?"]
        params: list[Any] = [conversation_id]

        if not include_system:
            where_clauses.append("role != 'system'")
        if role:
            where_clauses.append("role = ?")
            params.append(role)

        where_sql = " AND ".join(where_clauses)
        with self.connection() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) AS count FROM conversation_messages WHERE {where_sql}",
                tuple(params),
            ).fetchone()
            return int(row["count"]) if row else 0

    def get_latest_summary(self, conversation_id: str) -> str | None:
        """获取会话最新摘要内容。"""
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT content
                FROM conversation_messages
                WHERE conversation_id = ? AND is_summary = 1
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (conversation_id,),
            ).fetchone()
            return str(row["content"]) if row else None

    def save_summary(self, conversation_id: str, summary: str):
        """保存会话摘要（覆盖旧摘要）。"""
        self.add_conversation_message(
            conversation_id=conversation_id,
            role="system",
            content=summary,
            citations=[],
            token_estimate=max(1, len(summary) // 4),
            is_summary=True,
        )

    def count_recent_clarifications(self, conversation_id: str, limit: int = 2) -> int:
        """统计最近连续澄清消息数量，用于避免无限反问。"""
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT is_clarification
                FROM conversation_messages
                WHERE conversation_id = ? AND role = 'assistant'
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (conversation_id, limit),
            ).fetchall()

        count = 0
        for row in rows:
            if bool(row["is_clarification"]):
                count += 1
            else:
                break
        return count
