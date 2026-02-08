"""SQLite database for file index state management"""

import sqlite3
from pathlib import Path
from datetime import datetime
from contextlib import contextmanager
from typing import Iterator

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

CREATE INDEX IF NOT EXISTS idx_files_status ON files(status);
CREATE INDEX IF NOT EXISTS idx_files_book_id ON files(book_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
"""


class Database:
    """SQLite database manager for file index state"""
    
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
