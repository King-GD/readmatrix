"""Markdown parser with frontmatter extraction"""

import frontmatter
from pathlib import Path
from dataclasses import dataclass

from ..models import Document
from .scanner import compute_file_hash


def parse_markdown(file_path: Path, source_type: str = "markdown") -> Document:
    """
    Parse a markdown file with frontmatter.
    
    Args:
        file_path: Path to the markdown file
        source_type: "weread" or "markdown"
    
    Returns:
        Document object with parsed content and metadata
    """
    content = file_path.read_text(encoding="utf-8")
    post = frontmatter.loads(content)
    
    # Extract metadata from frontmatter
    metadata = dict(post.metadata)
    
    # Get title from frontmatter or filename
    title = metadata.get("title") or file_path.stem
    
    # For WeRead, also try to extract from content
    if source_type == "weread" and not metadata.get("title"):
        # WeRead format has title in first heading or abstract
        lines = post.content.split("\n")
        for line in lines:
            if line.startswith("# ") and "元数据" not in line:
                title = line[2:].strip()
                break
            if "> [!abstract]" in line:
                # Next line or part after ] might have title
                title_part = line.split("]")[-1].strip()
                if title_part:
                    title = title_part
                    break
    
    stat = file_path.stat()
    
    return Document(
        path=file_path,
        title=title,
        content=post.content,
        hash=compute_file_hash(file_path),
        mtime=stat.st_mtime,
        source_type=source_type,
        metadata=metadata,
    )
