"""Tests for offline evaluation reporting."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import json

from typer.testing import CliRunner

import readmatrix.eval as eval_module
from readmatrix.eval import app, compare_reports, default_cases_path
from readmatrix.models import Chunk


runner = CliRunner()


class FakeRetriever:
    def search(self, query: str, top_k: int = 5, book_id=None, book_title=None):
        return [
            Chunk(
                chunk_id="chunk-1",
                block_id="block-1",
                content="混合检索可以提升召回率",
                source_path="E:/vault/rag.md",
                title_path=["第一章"],
                book_id="book-1",
                book_title="高阶 RAG",
                author=None,
                highlight_time=None,
            )
        ]


class FakeQAEngine:
    def ask(self, query: str):
        citation = SimpleNamespace(book_title="评测手册")
        return "这是一条带引用的回答", [citation]


def test_default_case_paths_exist():
    assert default_cases_path("retrieval").exists()
    assert default_cases_path("generation").exists()


def test_run_retrieval_writes_json_report(tmp_path: Path, monkeypatch):
    cases_path = tmp_path / "retrieval.jsonl"
    cases_path.write_text(
        json.dumps(
            {
                "id": "retrieval-case",
                "query": "混合检索",
                "expected": {"must_include": ["混合检索"]},
            },
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )
    output_path = tmp_path / "retrieval-report.json"

    monkeypatch.setattr(eval_module, "Retriever", FakeRetriever)

    result = runner.invoke(
        app,
        [
            "run",
            "--mode",
            "retrieval",
            "--cases",
            str(cases_path),
            "--output",
            str(output_path),
        ],
    )

    assert result.exit_code == 0
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["mode"] == "retrieval"
    assert report["summary"]["hit_rate"] == 1.0
    assert report["results"][0]["hit"] is True


def test_run_generation_writes_json_report(tmp_path: Path, monkeypatch):
    cases_path = tmp_path / "generation.jsonl"
    cases_path.write_text(
        json.dumps(
            {
                "id": "generation-case",
                "query": "为什么做评测",
                "expected": {"book_title": ["评测"]},
            },
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )
    output_path = tmp_path / "generation-report.json"

    monkeypatch.setattr(eval_module, "QAEngine", FakeQAEngine)

    result = runner.invoke(
        app,
        [
            "run",
            "--mode",
            "generation",
            "--cases",
            str(cases_path),
            "--output",
            str(output_path),
        ],
    )

    assert result.exit_code == 0
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["mode"] == "generation"
    assert report["summary"]["citation_recall"] == 1.0
    assert report["results"][0]["citation_hit"] is True


def test_compare_reports_marks_improvements_and_regressions():
    baseline = {
        "mode": "retrieval",
        "summary": {"hit_rate": 0.5, "mrr": 0.5},
        "results": [
            {"id": "a", "mrr": 1.0},
            {"id": "b", "mrr": 0.0},
        ],
    }
    current = {
        "mode": "retrieval",
        "summary": {"hit_rate": 1.0, "mrr": 0.75},
        "results": [
            {"id": "a", "mrr": 0.5},
            {"id": "b", "mrr": 1.0},
        ],
    }

    comparison = compare_reports(baseline, current)

    assert comparison["summary_delta"]["hit_rate"] == 0.5
    assert comparison["summary_delta"]["mrr"] == 0.25
    assert comparison["improved_cases"] == ["b"]
    assert comparison["regressed_cases"] == ["a"]
