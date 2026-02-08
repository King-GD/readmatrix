"""Data models for ReadMatrix"""

from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime
from urllib.parse import quote

from .config import get_settings


@dataclass
class Document:
    """Represents a parsed markdown file"""
    path: Path
    title: str
    content: str
    hash: str
    mtime: float
    source_type: str  # "weread" | "markdown"
    metadata: dict = field(default_factory=dict)
    
    @property
    def book_id(self) -> str | None:
        return self.metadata.get("bookId")
    
    @property
    def author(self) -> str | None:
        return self.metadata.get("author")


@dataclass
class Chunk:
    """Represents a text chunk for indexing"""
    chunk_id: str           # sha256(source_path + "^" + block_id)[:16]
    block_id: str           # Original ^bookId-chapter-start-end
    content: str            # Text content
    source_path: str        # Path to source file
    title_path: list[str]   # Chapter hierarchy
    book_id: str
    book_title: str
    author: str | None
    highlight_time: str | None
    distance: float | None = None
    
    def to_metadata(self) -> dict:
        """Convert to ChromaDB metadata format"""
        return {
            "block_id": self.block_id,
            "source_path": self.source_path,
            "title_path": "|".join(self.title_path),  # ChromaDB doesn't support list
            "book_id": self.book_id,
            "book_title": self.book_title,
            "author": self.author or "",
            "highlight_time": self.highlight_time or "",
        }
    
    @classmethod
    def from_metadata(
        cls,
        chunk_id: str,
        content: str,
        metadata: dict,
        distance: float | None = None,
    ) -> "Chunk":
        """Create from ChromaDB metadata"""
        return cls(
            chunk_id=chunk_id,
            block_id=metadata.get("block_id", ""),
            content=content,
            source_path=metadata.get("source_path", ""),
            title_path=metadata.get("title_path", "").split("|"),
            book_id=metadata.get("book_id", ""),
            book_title=metadata.get("book_title", ""),
            author=metadata.get("author") or None,
            highlight_time=metadata.get("highlight_time") or None,
            distance=distance,
        )


@dataclass
class Citation:
    """Represents a citation in the answer"""
    id: int                     # [1], [2], ...
    chunk_id: str               # Global unique ID
    block_id: str               # Obsidian anchor
    source_path: str
    title_path: list[str]
    snippet: str                # 200-400 chars
    book_id: str
    book_title: str
    author: str | None
    highlight_time: str | None
    obsidian_uri: str | None
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "chunk_id": self.chunk_id,
            "block_id": self.block_id,
            "source_path": self.source_path,
            "title_path": self.title_path,
            "snippet": self.snippet,
            "book_id": self.book_id,
            "book_title": self.book_title,
            "author": self.author,
            "highlight_time": self.highlight_time,
            "obsidian_uri": self.obsidian_uri,
        }
    
    @classmethod
    def from_chunk(
        cls,
        chunk: Chunk,
        citation_id: int,
        vault_name: str | None = None,
    ) -> "Citation":
        """Create citation from chunk"""
        obsidian_uri = _build_obsidian_uri(
            chunk.source_path,
            chunk.block_id,
            vault_name=vault_name,
        )
        
        return cls(
            id=citation_id,
            chunk_id=chunk.chunk_id,
            block_id=chunk.block_id,
            source_path=chunk.source_path,
            title_path=chunk.title_path,
            snippet=chunk.content[:400],
            book_id=chunk.book_id,
            book_title=chunk.book_title,
            author=chunk.author,
            highlight_time=chunk.highlight_time,
            obsidian_uri=obsidian_uri,
        )


def _build_obsidian_uri(
    source_path: str,
    block_id: str | None,
    vault_name: str | None = None,
) -> str | None:
    """根据源文件路径构建 Obsidian URI，仅在存在锚点时追加 block_id。"""
    if not source_path:
        return None

    settings = get_settings()
    vault_path = settings.vault_path.resolve()

    try:
        relative_path = Path(source_path).resolve().relative_to(vault_path)
    except Exception:
        relative_path = Path(source_path).name

    vault = vault_name or vault_path.name
    file_path = quote(str(relative_path).replace("\\", "/"), safe="/")
    obsidian_uri = f"obsidian://open?vault={quote(vault)}&file={file_path}"

    if block_id and _has_block_anchor(Path(source_path), block_id):
        obsidian_uri += f"#^{block_id}"
    else:
        heading_anchor = _get_heading_anchor(Path(source_path))
        if heading_anchor:
            obsidian_uri += f"#{heading_anchor}"

    return obsidian_uri


def _has_block_anchor(file_path: Path, block_id: str) -> bool:
    """判断文件中是否存在指定的 Obsidian block anchor。"""
    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception:
        return False
    return f"^{block_id}" in content


def _get_heading_anchor(file_path: Path) -> str | None:
    """获取可跳转的标题锚点（优先使用章节标题）。"""
    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception:
        return None

    # 优先取第一个二级标题，其次一级标题
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            return quote(stripped[3:].strip())
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return quote(stripped[2:].strip())

    return None


@dataclass
class FileRecord:
    """SQLite file index record"""
    path: str
    hash: str
    mtime: float
    status: str  # "indexed" | "pending" | "error"
    source_type: str  # "weread" | "markdown"
    book_id: str | None
    last_error: str | None
    updated_at: datetime = field(default_factory=datetime.now)
