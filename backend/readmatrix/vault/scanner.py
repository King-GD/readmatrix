"""Vault file scanner with incremental update detection"""

import hashlib
from pathlib import Path
from dataclasses import dataclass
from typing import Iterator

from ..config import get_settings


@dataclass
class FileInfo:
    """File information for change detection"""
    path: Path
    hash: str
    mtime: float
    size: int


def compute_file_hash(file_path: Path) -> str:
    """Compute SHA256 hash of file content (first 16 chars)"""
    content = file_path.read_text(encoding="utf-8")
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def scan_directory(directory: Path, pattern: str = "*.md") -> Iterator[Path]:
    """Scan directory for markdown files"""
    if not directory.exists():
        return
    
    for file_path in directory.glob(pattern):
        if file_path.is_file():
            yield file_path


def get_file_info(file_path: Path) -> FileInfo:
    """Get file information for change detection"""
    stat = file_path.stat()
    return FileInfo(
        path=file_path,
        hash=compute_file_hash(file_path),
        mtime=stat.st_mtime,
        size=stat.st_size,
    )


def detect_source_type(file_path: Path) -> str:
    """Detect if file is WeRead format or generic markdown"""
    try:
        content = file_path.read_text(encoding="utf-8")[:500]
        # WeRead files have specific frontmatter
        if "doc_type: weread-highlights-reviews" in content:
            return "weread"
        if "bookId:" in content and "📌" in content:
            return "weread"
    except Exception:
        pass
    return "markdown"


def scan_vault(vault_path: Path | None = None) -> Iterator[tuple[Path, str]]:
    """
    Scan vault for all markdown files with their source types.
    
    Yields:
        Tuple of (file_path, source_type)
    """
    settings = get_settings()
    vault = vault_path or settings.vault_path
    
    if not vault.exists():
        raise FileNotFoundError(f"Vault path does not exist: {vault}")
    
    # Scan WeRead folder specifically
    weread_path = vault / settings.weread_folder
    if weread_path.exists():
        for file_path in scan_directory(weread_path):
            yield file_path, "weread"
    
    # Scan other markdown files (excluding WeRead folder)
    for file_path in scan_directory(vault, "**/*.md"):
        # Skip WeRead folder (already scanned)
        if settings.weread_folder in file_path.parts:
            continue
        # Skip hidden folders
        if any(part.startswith(".") for part in file_path.parts):
            continue
        yield file_path, detect_source_type(file_path)


def get_files_needing_update(
    scanned_files: list[tuple[Path, str]],
    indexed_records: dict[str, tuple[str, float]],  # path -> (hash, mtime)
) -> tuple[list[tuple[Path, str]], list[str]]:
    """
    Determine which files need indexing and which should be removed.
    
    Args:
        scanned_files: List of (path, source_type) from scan
        indexed_records: Dict of path -> (hash, mtime) from SQLite
    
    Returns:
        Tuple of (files_to_index, paths_to_remove)
    """
    files_to_index = []
    current_paths = set()
    
    for file_path, source_type in scanned_files:
        path_str = str(file_path)
        current_paths.add(path_str)
        
        if path_str not in indexed_records:
            # New file
            files_to_index.append((file_path, source_type))
        else:
            # Check if file changed
            old_hash, old_mtime = indexed_records[path_str]
            try:
                stat = file_path.stat()
                # Quick check: mtime changed
                if stat.st_mtime != old_mtime:
                    # Verify with hash
                    new_hash = compute_file_hash(file_path)
                    if new_hash != old_hash:
                        files_to_index.append((file_path, source_type))
            except Exception:
                # File might be deleted or inaccessible
                pass
    
    # Files in index but not in scan = removed
    paths_to_remove = [p for p in indexed_records.keys() if p not in current_paths]
    
    return files_to_index, paths_to_remove
