"""Vault module - file scanning, parsing, and chunking"""

from .scanner import (
    scan_vault,
    get_file_info,
    compute_file_hash,
    get_files_needing_update,
    detect_source_type,
)
from .parser import parse_markdown
from .chunker import (
    chunk_weread_document,
    parse_weread_highlights,
    make_chunk_id,
)

__all__ = [
    "scan_vault",
    "get_file_info",
    "compute_file_hash",
    "get_files_needing_update",
    "detect_source_type",
    "parse_markdown",
    "chunk_weread_document",
    "parse_weread_highlights",
    "make_chunk_id",
]
