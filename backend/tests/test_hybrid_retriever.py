"""Tests for SQLite sparse retrieval and hybrid retriever behavior."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import readmatrix.indexer.manager as manager_module
import readmatrix.retriever as retriever_module
from readmatrix.indexer.database import Database
from readmatrix.indexer.manager import IndexManager
from readmatrix.models import Chunk, Document
from readmatrix.retrieval_fusion import reciprocal_rank_fusion
from readmatrix.retriever import Retriever


def make_chunk(
    chunk_id: str,
    content: str,
    *,
    source_path: str = "E:/vault/sample.md",
    book_id: str = "book-1",
    book_title: str = "RAG 实战",
    title_path: list[str] | None = None,
) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        block_id=f"block-{chunk_id}",
        content=content,
        source_path=source_path,
        title_path=title_path or ["第一章"],
        book_id=book_id,
        book_title=book_title,
        author=None,
        highlight_time=None,
    )


@dataclass
class FakeEmbedder:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(text))] for text in texts]


@dataclass
class FakeReranker:
    called: bool = False

    def rerank(self, query: str, chunks: list[Chunk], top_k: int | None = None, model: str = "") -> list[Chunk]:
        self.called = True
        return chunks[:top_k] if top_k else chunks


@dataclass
class FakeVectorStore:
    search_results: list[Chunk]
    added_chunks: list[Chunk] | None = None
    deleted_paths: list[str] | None = None

    def search(self, query_embedding, top_k=5, book_id=None, book_title=None) -> list[Chunk]:
        return self.search_results[:top_k]

    def add_chunks(self, chunks: list[Chunk], embeddings: list[list[float]]):
        if self.added_chunks is None:
            self.added_chunks = []
        self.added_chunks.extend(chunks)

    def delete_by_source_path(self, source_path: str):
        if self.deleted_paths is None:
            self.deleted_paths = []
        self.deleted_paths.append(source_path)

    def get_by_source(self, source_path: str, limit: int = 50) -> list[Chunk]:
        return [chunk for chunk in self.search_results if chunk.source_path == source_path][:limit]

    def clear(self):
        self.search_results = []


def make_settings(**overrides):
    defaults = {
        "enable_reranker": False,
        "retrieval_max_distance": None,
        "context_window": 0,
        "retrieval_mode": "hybrid",
        "enable_sparse_retrieval": True,
        "dense_top_k": 20,
        "sparse_top_k": 20,
        "fusion_top_k": 20,
        "reranker_model": "test-model",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_sparse_search_returns_exact_match(tmp_path: Path):
    db = Database(db_path=tmp_path / "sparse.db")
    chunk = make_chunk("chunk-1", "混合检索可以提升召回效果", book_title="高阶 RAG")
    db.upsert_sparse_chunks([chunk])

    results = db.search_sparse_chunks("混合检索", limit=5)

    assert [item.chunk_id for item in results] == ["chunk-1"]
    assert results[0].book_title == "高阶 RAG"


def test_reciprocal_rank_fusion_prefers_multi_source_hits():
    shared = make_chunk("shared", "共享结果")
    dense_only = make_chunk("dense", "向量独有结果")
    sparse_only = make_chunk("sparse", "关键词独有结果")

    fused = reciprocal_rank_fusion(
        [
            [shared, dense_only],
            [sparse_only, shared],
        ],
        top_k=3,
    )

    assert [chunk.chunk_id for chunk in fused] == ["shared", "sparse", "dense"]


def test_hybrid_retriever_returns_sparse_only_hit(tmp_path: Path, monkeypatch):
    db = Database(db_path=tmp_path / "hybrid.db")
    sparse_chunk = make_chunk("chunk-sparse", "GraphRAG 是一种图增强检索方法", book_title="RAG 进阶")
    db.upsert_sparse_chunks([sparse_chunk])

    monkeypatch.setattr(retriever_module, "get_settings", lambda: make_settings())

    retriever = Retriever(
        vectorstore=FakeVectorStore(search_results=[]),
        db=db,
        embedder=FakeEmbedder(),
        reranker=FakeReranker(),
    )

    results = retriever.search("GraphRAG", top_k=3)

    assert [chunk.chunk_id for chunk in results] == ["chunk-sparse"]


def test_dense_mode_skips_sparse_retrieval(tmp_path: Path, monkeypatch):
    db = Database(db_path=tmp_path / "dense.db")
    dense_chunk = make_chunk("chunk-dense", "向量检索命中的内容")

    def fail_sparse(*args, **kwargs):
        raise AssertionError("sparse retrieval should not be called in dense mode")

    monkeypatch.setattr(db, "search_sparse_chunks", fail_sparse)
    monkeypatch.setattr(
        retriever_module,
        "get_settings",
        lambda: make_settings(retrieval_mode="dense"),
    )

    retriever = Retriever(
        vectorstore=FakeVectorStore(search_results=[dense_chunk]),
        db=db,
        embedder=FakeEmbedder(),
        reranker=FakeReranker(),
    )

    results = retriever.search("向量检索", top_k=3)

    assert [chunk.chunk_id for chunk in results] == ["chunk-dense"]


def test_index_manager_writes_sparse_index(tmp_path: Path, monkeypatch):
    db = Database(db_path=tmp_path / "index.db")
    vectorstore = FakeVectorStore(search_results=[])
    file_path = tmp_path / "note.md"
    file_path.write_text("# title", encoding="utf-8")

    document = Document(
        path=file_path,
        title="索引测试",
        content="这是一段用于混合检索测试的笔记内容",
        hash="hash-1",
        mtime=1.0,
        source_type="markdown",
        metadata={},
    )

    monkeypatch.setattr(manager_module, "parse_markdown", lambda path, source_type: document)
    monkeypatch.setattr(manager_module, "get_embedding_provider", lambda: FakeEmbedder())

    manager = IndexManager(db=db, vectorstore=vectorstore)
    manager._index_file(file_path, "markdown")

    results = db.search_sparse_chunks("混合检索测试", limit=5)

    assert vectorstore.added_chunks is not None
    assert len(vectorstore.added_chunks) == 1
    assert [chunk.book_title for chunk in results] == ["索引测试"]


def test_incremental_update_removes_sparse_chunks_for_deleted_files(tmp_path: Path, monkeypatch):
    db = Database(db_path=tmp_path / "delete.db")
    source_path = "E:/vault/delete-me.md"
    chunk = make_chunk("chunk-delete", "删除后不应再被关键词命中", source_path=source_path)
    db.upsert_sparse_chunks([chunk])

    vectorstore = FakeVectorStore(search_results=[])
    manager = IndexManager(db=db, vectorstore=vectorstore)

    monkeypatch.setattr(manager_module, "scan_vault", lambda: [])
    monkeypatch.setattr(manager_module, "get_files_needing_update", lambda scanned, indexed: ([], [source_path]))

    stats = manager.incremental_update()

    assert stats["removed"] == 1
    assert vectorstore.deleted_paths == [source_path]
    assert db.search_sparse_chunks("删除后", limit=5) == []
