"""RAG 评测工具（离线检索评测）"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any
import json

from rich.console import Console
from rich.table import Table
import typer

from .retriever import Retriever
from .qa import QAEngine


console = Console()
app = typer.Typer(help="RAG 评测工具")


@dataclass
class EvalCase:
    """评测样例定义。"""

    case_id: str
    query: str
    expected: dict[str, Any]


def _normalize_text(text: str) -> str:
    """规范化文本，便于路径或标题匹配。"""
    return text.replace("\\", "/").strip().lower()


def _matches_expected(chunk, expected: dict[str, Any]) -> bool:
    """判断检索结果是否满足期望条件。"""
    if not expected:
        return False

    book_titles = [_normalize_text(x) for x in expected.get("book_title", [])]
    source_paths = [_normalize_text(x) for x in expected.get("source_path", [])]
    must_include = expected.get("must_include", [])

    match = True
    if book_titles:
        match = match and any(
            bt in _normalize_text(chunk.book_title) for bt in book_titles
        )
    if source_paths:
        match = match and any(
            sp in _normalize_text(chunk.source_path) for sp in source_paths
        )
    if must_include:
        match = match and all(keyword in chunk.content for keyword in must_include)

    return match


def load_cases(cases_path: Path) -> list[EvalCase]:
    """从 jsonl 文件加载评测样例。"""
    cases = []
    for line in cases_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        cases.append(
            EvalCase(
                case_id=str(payload.get("id", "")),
                query=str(payload.get("query", "")),
                expected=payload.get("expected", {}),
            )
        )
    return cases


def evaluate_retrieval(case: EvalCase, retriever: Retriever, top_k: int) -> dict[str, Any]:
    """评估单条样例并返回检索结果字典。"""
    chunks = retriever.search(query=case.query, top_k=top_k)
    rank = None
    matched_title = ""

    for idx, chunk in enumerate(chunks, 1):
        if _matches_expected(chunk, case.expected):
            rank = idx
            matched_title = chunk.book_title
            break

    distances = [c.distance for c in chunks if c.distance is not None]
    avg_distance = mean(distances) if distances else None

    return {
        "id": case.case_id,
        "query": case.query,
        "hit": rank is not None,
        "rank": rank,
        "mrr": 0 if rank is None else 1 / rank,
        "matched_title": matched_title,
        "avg_distance": avg_distance,
    }


def evaluate_generation(case: EvalCase, qa_engine: QAEngine) -> dict[str, Any]:
    """评估单条样例的生成质量（引用召回）。"""
    answer, citations = qa_engine.ask(query=case.query)

    citation_hit = False
    matched_titles = []

    if case.expected:
        book_titles = [_normalize_text(x) for x in case.expected.get("book_title", [])]

        for cit in citations:
            cit_book_title = _normalize_text(cit.book_title)
            # Check if this citation matches any expected book title
            if any(bt in cit_book_title for bt in book_titles):
                citation_hit = True
                matched_titles.append(cit.book_title)

    return {
        "id": case.case_id,
        "query": case.query,
        "citation_hit": citation_hit,
        "citation_count": len(citations),
        "matched_titles": list(set(matched_titles)),
        "answer_preview": answer[:50].replace("\n", " ") + "...",
    }


def summarize_results(results: list[dict[str, Any]], mode: str) -> dict[str, float]:
    """汇总评测指标。"""
    if not results:
        return {}

    if mode == "retrieval":
        hit_rate = sum(1 for r in results if r["hit"]) / len(results)
        mrr = sum(r["mrr"] for r in results) / len(results)
        return {"hit_rate": hit_rate, "mrr": mrr}
    else:  # generation
        citation_recall = sum(1 for r in results if r["citation_hit"]) / len(results)
        avg_citations = sum(r["citation_count"] for r in results) / len(results)
        return {"citation_recall": citation_recall, "avg_citations": avg_citations}


@app.command()
def run(
    cases: Path = typer.Option(
        Path("eval_cases.jsonl"),
        "--cases",
        help="评测样例文件（jsonl）",
    ),
    top_k: int = typer.Option(5, "--top-k", help="每条样例的检索数量"),
    mode: str = typer.Option("retrieval", "--mode", "-m", help="模式: retrieval | generation"),
    limit: int = typer.Option(0, "--limit", "-n", help="限制测试数量（0为不限制）"),
) -> None:
    """运行离线 RAG 评测（检索或生成）。"""
    cases_path = cases
    if not cases_path.is_absolute():
        cases_path = Path.cwd() / cases_path
    if not cases_path.exists():
        console.print(f"[red]评测文件不存在: {cases_path}[/red]")
        raise typer.Exit(code=1)

    case_list = load_cases(cases_path)
    if not case_list:
        console.print("[yellow]评测样例为空[/yellow]")
        return

    if limit > 0:
        case_list = case_list[:limit]

    console.print(f"[bold]Running {mode} evaluation on {len(case_list)} cases...[/bold]")

    if mode == "retrieval":
        retriever = Retriever()
        results = [evaluate_retrieval(case, retriever, top_k) for case in case_list]
        summary = summarize_results(results, mode)

        table = Table(show_header=True)
        table.add_column("ID", style="cyan")
        table.add_column("Hit")
        table.add_column("Rank")
        table.add_column("MRR")
        table.add_column("Matched")

        for result in results:
            table.add_row(
                result["id"],
                "Y" if result["hit"] else "N",
                "-" if result["rank"] is None else str(result["rank"]),
                f"{result['mrr']:.2f}",
                result["matched_title"][:20],
            )

        console.print(table)
        console.print(
            f"\n[bold]Summary[/bold]  hit_rate={summary['hit_rate']:.2f}  mrr={summary['mrr']:.2f}"
        )

    elif mode == "generation":
        qa_engine = QAEngine()
        results = []

        with typer.progressbar(case_list, label="Generating answers") as progress:
            for case in progress:
                results.append(evaluate_generation(case, qa_engine))

        summary = summarize_results(results, mode)

        table = Table(show_header=True)
        table.add_column("ID", style="cyan")
        table.add_column("Cit. Hit")
        table.add_column("Citations")
        table.add_column("Matched Books")
        table.add_column("Answer Preview")

        for result in results:
            table.add_row(
                result["id"],
                "Y" if result["citation_hit"] else "N",
                str(result["citation_count"]),
                ", ".join(result["matched_titles"])[:30],
                result["answer_preview"],
            )

        console.print(table)
        console.print(
            f"\n[bold]Summary[/bold]  citation_recall={summary['citation_recall']:.2f}  avg_citations={summary['avg_citations']:.1f}"
        )

    else:
        console.print(f"[red]Unknown mode: {mode}[/red]")
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
