"""WeRead highlight chunker with section-first parsing (fixes chapter loss bug)"""

import re
import hashlib
from pathlib import Path

from ..models import Document, Chunk


def make_chunk_id(source_path: str, block_id: str) -> str:
    """Generate globally unique chunk_id from path and block_id"""
    combined = f"{source_path}^{block_id}"
    return hashlib.sha256(combined.encode()).hexdigest()[:16]


def _unique_chunk_id(
    source_path: str,
    block_key: str,
    counts: dict[str, int],
) -> str:
    """生成唯一 chunk_id，不修改原始 block_id。"""
    counts[block_key] = counts.get(block_key, 0) + 1
    if counts[block_key] > 1:
        block_key = f"{block_key}-{counts[block_key]}"
    return make_chunk_id(source_path, block_key)


def parse_weread_highlights(document: Document) -> list[Chunk]:
    """
    Parse WeRead format file and extract highlights as chunks.

    Strategy: Split by section first, then extract highlights within each section.
    This fixes the bug where all highlights get the last chapter's title.

    Args:
        document: Parsed Document object

    Returns:
        List of Chunk objects
    """
    chunks = []
    content = document.content
    source_path = str(document.path)
    block_counts: dict[str, int] = {}

    book_id = document.metadata.get("bookId", "")
    book_title = document.metadata.get("title") or document.title
    author = document.metadata.get("author", "")

    # 1. Split content by chapter headings (### )
    # Use regex to split while keeping the delimiter
    sections = re.split(r"\n(?=### )", content)

    # 2. Highlight pattern - time is optional, block_id is optional
    # Format: > 📌 content \n> ⏱time ^id  OR  > 📌 content ^id
    highlight_pattern = re.compile(
        r"> 📌 (.+?)\s*\n"                      # Highlight content
        r"(?:> ⏱(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}))?\s*"  # Optional timestamp
        r"\^?([\w-]+)?",                         # Optional block_id
        re.DOTALL,
    )

    for section in sections:
        # Extract chapter title from section
        chapter_match = re.match(r"^### (.+?)$", section, re.MULTILINE)
        current_chapter = chapter_match.group(1).strip() if chapter_match else None

        # Skip sections without highlights
        if "📌" not in section:
            continue

        # Extract all highlights in this section
        for match in highlight_pattern.finditer(section):
            text = match.group(1).strip()
            # Clean up text: remove trailing > symbols and whitespace
            text = re.sub(r"\s*>\s*$", "", text)
            text = text.strip()

            if not text:
                continue

            time = match.group(2)  # May be None
            block_id = match.group(3)

            # Generate block_id if missing
            if not block_id:
                block_id = hashlib.sha256(text.encode()).hexdigest()[:12]

            # 保证 chunk_id 唯一，不修改原始 block_id
            chunk_id = _unique_chunk_id(source_path, block_id, block_counts)

            # Build title_path
            title_path = [current_chapter] if current_chapter else []

            chunk = Chunk(
                chunk_id=chunk_id,
                block_id=block_id,
                content=text,
                source_path=source_path,
                title_path=title_path,
                book_id=book_id,
                book_title=book_title,
                author=author or None,
                highlight_time=time,
            )
            chunks.append(chunk)

    return chunks


def parse_weread_notes(document: Document) -> list[Chunk]:
    """
    Parse WeRead reading notes (💭 comments).

    These are structured differently:
    > 📌 original text ^noteId
        - 💭 note content
        - ⏱time
    """
    chunks = []
    content = document.content
    source_path = str(document.path)
    block_counts: dict[str, int] = {}

    book_id = document.metadata.get("bookId", "")
    book_title = document.metadata.get("title") or document.title
    author = document.metadata.get("author", "")

    # Note pattern
    note_pattern = re.compile(
        r"> 📌 (.+?)\s+\^([\w-]+)\s*\n"        # Original text with ID
        r"\s*- 💭 (.+?)\s*\n"                   # Note content
        r"\s*- ⏱(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})",  # Time
        re.DOTALL,
    )

    for match in note_pattern.finditer(content):
        original_text = match.group(1).strip()
        note_id = match.group(2)
        note_content = match.group(3).strip()
        time = match.group(4)

        # Combine original text and note for better context
        combined_text = f"原文：{original_text}\n笔记：{note_content}"

        block_key = f"note-{note_id}"
        chunk_id = _unique_chunk_id(source_path, block_key, block_counts)

        chunk = Chunk(
            chunk_id=chunk_id,
            block_id=note_id,
            content=combined_text,
            source_path=source_path,
            title_path=["读书笔记"],
            book_id=book_id,
            book_title=book_title,
            author=author or None,
            highlight_time=time,
        )
        chunks.append(chunk)

    return chunks


def chunk_weread_document(document: Document) -> list[Chunk]:
    """
    Main entry point: chunk a WeRead document into highlights and notes.
    """
    chunks = []

    # Extract highlights
    chunks.extend(parse_weread_highlights(document))

    # Extract notes
    chunks.extend(parse_weread_notes(document))

    return chunks
