"""Utilities for combining retrieval result lists."""

from __future__ import annotations

from collections import defaultdict

from .models import Chunk


def reciprocal_rank_fusion(
    ranked_lists: list[list[Chunk]],
    top_k: int,
    k: int = 60,
) -> list[Chunk]:
    """Fuse ranked lists using Reciprocal Rank Fusion."""
    if top_k <= 0:
        return []

    scores: dict[str, float] = defaultdict(float)
    canonical: dict[str, Chunk] = {}

    for ranked in ranked_lists:
        for rank, chunk in enumerate(ranked, start=1):
            canonical.setdefault(chunk.chunk_id, chunk)
            scores[chunk.chunk_id] += 1.0 / (k + rank)

    ordered_ids = sorted(scores, key=lambda chunk_id: scores[chunk_id], reverse=True)
    return [canonical[chunk_id] for chunk_id in ordered_ids[:top_k]]
