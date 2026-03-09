"""Offline RAG evaluation helpers and CLI."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any
import json

from rich.console import Console
from rich.table import Table
import typer

from .qa import QAEngine
from .retriever import Retriever


console = Console()
app = typer.Typer(help="Offline RAG evaluation tools")

EVAL_ROOT = Path(__file__).resolve().parent.parent / "evals"
CASES_ROOT = EVAL_ROOT / "cases"
REPORTS_ROOT = EVAL_ROOT / "reports"


@dataclass
class EvalCase:
    """Definition of one offline evaluation case."""

    case_id: str
    query: str
    expected: dict[str, Any]


def _normalize_text(text: str) -> str:
    return text.replace("\\", "/").strip().lower()


def _matches_expected(chunk, expected: dict[str, Any]) -> bool:
    if not expected:
        return False

    book_titles = [_normalize_text(x) for x in expected.get("book_title", [])]
    source_paths = [_normalize_text(x) for x in expected.get("source_path", [])]
    must_include = expected.get("must_include", [])

    match = True
    if book_titles:
        match = match and any(bt in _normalize_text(chunk.book_title) for bt in book_titles)
    if source_paths:
        match = match and any(sp in _normalize_text(chunk.source_path) for sp in source_paths)
    if must_include:
        match = match and all(keyword in chunk.content for keyword in must_include)
    return match


def default_cases_path(mode: str) -> Path:
    """Return the default case file for a mode."""
    if mode == "retrieval":
        return CASES_ROOT / "retrieval.jsonl"
    if mode == "generation":
        return CASES_ROOT / "generation.jsonl"
    raise ValueError(f"Unsupported mode for default cases: {mode}")


def default_report_path(mode: str) -> Path:
    """Return a timestamped report file path."""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return REPORTS_ROOT / f"{mode}-{timestamp}.json"


def load_cases(cases_path: Path) -> list[EvalCase]:
    """Load evaluation cases from a JSONL file."""
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
    """Evaluate a retrieval case and return rank-oriented metrics."""
    chunks = retriever.search(query=case.query, top_k=top_k)
    rank = None
    matched_title = ""

    for idx, chunk in enumerate(chunks, 1):
        if _matches_expected(chunk, case.expected):
            rank = idx
            matched_title = chunk.book_title
            break

    distances = [chunk.distance for chunk in chunks if chunk.distance is not None]
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
    """Evaluate answer grounding using citations returned by the QA engine."""
    answer, citations = qa_engine.ask(query=case.query)

    citation_hit = False
    matched_titles: list[str] = []
    book_titles = [_normalize_text(x) for x in case.expected.get("book_title", [])]

    for citation in citations:
        citation_book_title = _normalize_text(citation.book_title)
        if any(book_title in citation_book_title for book_title in book_titles):
            citation_hit = True
            matched_titles.append(citation.book_title)

    preview = answer[:80].replace("\n", " ")
    return {
        "id": case.case_id,
        "query": case.query,
        "citation_hit": citation_hit,
        "citation_count": len(citations),
        "matched_titles": sorted(set(matched_titles)),
        "answer_preview": preview + ("..." if len(answer) > 80 else ""),
    }


def summarize_results(results: list[dict[str, Any]], mode: str) -> dict[str, float]:
    """Aggregate retrieval or generation metrics."""
    if not results:
        return {}

    if mode == "retrieval":
        hit_rate = sum(1 for result in results if result["hit"]) / len(results)
        mrr = sum(result["mrr"] for result in results) / len(results)
        recall_at_k = hit_rate
        return {"hit_rate": hit_rate, "mrr": mrr, "recall_at_k": recall_at_k}

    citation_recall = sum(1 for result in results if result["citation_hit"]) / len(results)
    avg_citations = sum(result["citation_count"] for result in results) / len(results)
    return {"citation_recall": citation_recall, "avg_citations": avg_citations}


def build_report(
    mode: str,
    cases_path: Path,
    results: list[dict[str, Any]],
    summary: dict[str, float],
    top_k: int,
) -> dict[str, Any]:
    """Build a machine-readable report payload."""
    return {
        "mode": mode,
        "generated_at": datetime.now().isoformat(),
        "cases_path": str(cases_path),
        "top_k": top_k,
        "case_count": len(results),
        "summary": summary,
        "results": results,
    }


def compare_reports(baseline_report: dict[str, Any], current_report: dict[str, Any]) -> dict[str, Any]:
    """Compare current report against a baseline report."""
    baseline_summary = baseline_report.get("summary", {})
    current_summary = current_report.get("summary", {})

    summary_delta = {}
    for key, value in current_summary.items():
        baseline_value = baseline_summary.get(key)
        if isinstance(value, (int, float)) and isinstance(baseline_value, (int, float)):
            summary_delta[key] = value - baseline_value

    baseline_results = {item["id"]: item for item in baseline_report.get("results", [])}
    improved: list[str] = []
    regressed: list[str] = []
    unchanged: list[str] = []

    for result in current_report.get("results", []):
        baseline_result = baseline_results.get(result["id"])
        if not baseline_result:
            continue

        if current_report["mode"] == "retrieval":
            current_score = result.get("mrr", 0)
            baseline_score = baseline_result.get("mrr", 0)
        else:
            current_score = int(result.get("citation_hit", False))
            baseline_score = int(baseline_result.get("citation_hit", False))

        if current_score > baseline_score:
            improved.append(result["id"])
        elif current_score < baseline_score:
            regressed.append(result["id"])
        else:
            unchanged.append(result["id"])

    return {
        "summary_delta": summary_delta,
        "improved_cases": improved,
        "regressed_cases": regressed,
        "unchanged_cases": unchanged,
    }


def write_report(report: dict[str, Any], output_path: Path):
    """Persist report JSON to disk."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def run_mode(
    mode: str,
    *,
    cases_path: Path,
    top_k: int,
    limit: int,
) -> dict[str, Any]:
    """Run one evaluation mode and return a report payload."""
    case_list = load_cases(cases_path)
    if not case_list:
        raise ValueError(f"No evaluation cases found in {cases_path}")
    if limit > 0:
        case_list = case_list[:limit]

    if mode == "retrieval":
        retriever = Retriever()
        results = [evaluate_retrieval(case, retriever, top_k) for case in case_list]
    elif mode == "generation":
        qa_engine = QAEngine()
        results = [evaluate_generation(case, qa_engine) for case in case_list]
    else:
        raise ValueError(f"Unsupported mode: {mode}")

    summary = summarize_results(results, mode)
    return build_report(mode, cases_path, results, summary, top_k)


def _print_report(report: dict[str, Any]):
    """Print a compact terminal summary."""
    table = Table(show_header=True)
    table.add_column("ID", style="cyan")

    if report["mode"] == "retrieval":
        table.add_column("Hit")
        table.add_column("Rank")
        table.add_column("MRR")
        table.add_column("Matched")
        for result in report["results"]:
            table.add_row(
                result["id"],
                "Y" if result["hit"] else "N",
                "-" if result["rank"] is None else str(result["rank"]),
                f"{result['mrr']:.2f}",
                result["matched_title"][:20],
            )
    else:
        table.add_column("Citation Hit")
        table.add_column("Citations")
        table.add_column("Matched Books")
        table.add_column("Answer Preview")
        for result in report["results"]:
            table.add_row(
                result["id"],
                "Y" if result["citation_hit"] else "N",
                str(result["citation_count"]),
                ", ".join(result["matched_titles"])[:30],
                result["answer_preview"],
            )

    console.print(table)
    console.print(f"[bold]Summary[/bold] {json.dumps(report['summary'], ensure_ascii=False)}")


@app.command("_noop", hidden=True)
def _noop():
    """Hidden command to keep Typer in explicit subcommand mode."""


@app.command()
def run(
    cases: Path | None = typer.Option(
        None,
        "--cases",
        help="Path to a JSONL case file. Required for retrieval/generation if you do not want defaults.",
    ),
    top_k: int = typer.Option(5, "--top-k", help="Number of chunks to retrieve"),
    mode: str = typer.Option("retrieval", "--mode", "-m", help="retrieval | generation | all"),
    limit: int = typer.Option(0, "--limit", "-n", help="Limit number of cases, 0 means all"),
    output: Path | None = typer.Option(None, "--output", help="Path to write JSON report"),
    baseline: Path | None = typer.Option(None, "--baseline", help="Optional baseline report JSON to compare against"),
) -> None:
    """Run offline RAG evaluation and optionally write reports."""
    normalized_mode = mode.lower()

    if normalized_mode == "all":
        if cases is not None:
            console.print("[red]--cases cannot be used with mode=all. Use default split case files.[/red]")
            raise typer.Exit(code=1)

        retrieval_report = run_mode(
            "retrieval",
            cases_path=default_cases_path("retrieval"),
            top_k=top_k,
            limit=limit,
        )
        generation_report = run_mode(
            "generation",
            cases_path=default_cases_path("generation"),
            top_k=top_k,
            limit=limit,
        )

        combined_report = {
            "mode": "all",
            "generated_at": datetime.now().isoformat(),
            "reports": {
                "retrieval": retrieval_report,
                "generation": generation_report,
            },
        }
        target_path = output or default_report_path("all")
        write_report(combined_report, target_path)
        _print_report(retrieval_report)
        _print_report(generation_report)
        console.print(f"[green]Wrote report to {target_path}[/green]")
        return

    cases_path = cases or default_cases_path(normalized_mode)
    if not cases_path.exists():
        console.print(f"[red]Case file not found: {cases_path}[/red]")
        raise typer.Exit(code=1)

    report = run_mode(
        normalized_mode,
        cases_path=cases_path,
        top_k=top_k,
        limit=limit,
    )

    if baseline:
        if not baseline.exists():
            console.print(f"[red]Baseline report not found: {baseline}[/red]")
            raise typer.Exit(code=1)
        baseline_report = json.loads(baseline.read_text(encoding="utf-8"))
        report["comparison"] = compare_reports(baseline_report, report)

    target_path = output or default_report_path(normalized_mode)
    write_report(report, target_path)
    _print_report(report)
    console.print(f"[green]Wrote report to {target_path}[/green]")


if __name__ == "__main__":
    app()
