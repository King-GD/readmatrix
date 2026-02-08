"""CLI tool for ReadMatrix"""

import typer
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from pathlib import Path

app = typer.Typer(
    name="readmatrix",
    help="ReadMatrix - Local-first personal knowledge platform",
)
console = Console()


@app.command()
def doctor():
    """Run environment self-checks"""
    from .config import get_settings
    from .indexer import Database, VectorStore
    
    settings = get_settings()
    
    console.print("\n[bold]ReadMatrix Doctor[/bold]\n")
    
    table = Table(show_header=True)
    table.add_column("Check", style="cyan")
    table.add_column("Status")
    table.add_column("Details")
    
    all_passed = True
    
    # 1. Vault path
    vault_ok = settings.vault_path.exists()
    table.add_row(
        "Vault Path",
        "[green]✓[/green]" if vault_ok else "[red]✗[/red]",
        str(settings.vault_path),
    )
    if not vault_ok:
        all_passed = False
    
    # 2. WeRead folder
    weread_path = settings.weread_path
    weread_ok = weread_path.exists()
    md_count = len(list(weread_path.glob("*.md"))) if weread_ok else 0
    table.add_row(
        "WeRead Folder",
        "[green]✓[/green]" if weread_ok else "[red]✗[/red]",
        f"{md_count} files" if weread_ok else "Not found",
    )
    if not weread_ok:
        all_passed = False
    
    # 3. WeRead structure
    weread_valid = False
    if weread_ok and md_count > 0:
        sample = next(weread_path.glob("*.md"), None)
        if sample:
            try:
                content = sample.read_text(encoding="utf-8")[:1000]
                weread_valid = "bookId:" in content or "📌" in content
            except Exception:
                pass
    table.add_row(
        "WeRead Structure",
        "[green]✓[/green]" if weread_valid else "[yellow]?[/yellow]",
        "Valid format" if weread_valid else "Not detected",
    )
    
    # 4. SQLite
    sqlite_ok = False
    try:
        db = Database()
        db.get_file_count()
        sqlite_ok = True
    except Exception as e:
        pass
    table.add_row(
        "SQLite Database",
        "[green]✓[/green]" if sqlite_ok else "[red]✗[/red]",
        str(settings.sqlite_path),
    )
    if not sqlite_ok:
        all_passed = False
    
    # 5. ChromaDB
    chroma_ok = False
    try:
        vs = VectorStore()
        chroma_ok = vs.test_persistence()
    except Exception:
        pass
    table.add_row(
        "ChromaDB Storage",
        "[green]✓[/green]" if chroma_ok else "[red]✗[/red]",
        str(settings.chroma_path),
    )
    if not chroma_ok:
        all_passed = False
    
    # 6. LLM API (based on provider)
    llm_ok = False
    llm_provider = settings.llm_provider
    llm_message = "Not configured"
    
    if llm_provider == "siliconflow":
        if settings.siliconflow_api_key:
            try:
                import openai
                client = openai.OpenAI(
                    api_key=settings.siliconflow_api_key,
                    base_url=settings.siliconflow_base_url,
                )
                # Test with a simple models list request
                client.models.list()
                llm_ok = True
                llm_message = f"SiliconFlow connected"
            except Exception as e:
                llm_message = f"SiliconFlow error: {str(e)[:30]}"
    elif llm_provider == "openai":
        if settings.openai_api_key:
            try:
                import openai
                client = openai.OpenAI(api_key=settings.openai_api_key)
                client.models.list()
                llm_ok = True
                llm_message = "OpenAI connected"
            except Exception as e:
                llm_message = f"OpenAI error: {str(e)[:30]}"
    elif llm_provider == "ollama":
        try:
            import httpx
            response = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=5.0)
            if response.status_code == 200:
                llm_ok = True
                llm_message = "Ollama connected"
        except Exception:
            llm_message = "Ollama not reachable"
    
    table.add_row(
        f"LLM API ({llm_provider})",
        "[green]✓[/green]" if llm_ok else "[red]✗[/red]",
        llm_message,
    )
    if not llm_ok:
        all_passed = False
    
    console.print(table)
    
    if all_passed:
        console.print("\n[green]✓ All checks passed![/green]\n")
    else:
        console.print("\n[red]✗ Some checks failed.[/red]\n")
        raise typer.Exit(code=1)


@app.command()
def index(
    full: bool = typer.Option(False, "--full", "-f", help="Full rebuild"),
):
    """Build or update the search index"""
    from .indexer import IndexManager
    
    manager = IndexManager()
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Indexing...", total=None)
        
        def callback(current: int, total: int, message: str):
            progress.update(task, description=f"[{current}/{total}] {message}")
        
        if full:
            console.print("[bold]Full rebuild...[/bold]")
            stats = manager.full_rebuild(progress_callback=callback)
        else:
            console.print("[bold]Incremental update...[/bold]")
            stats = manager.incremental_update(progress_callback=callback)
    
    console.print("\n[bold green]Indexing complete![/bold green]")
    console.print(f"  Files indexed: {stats.get('indexed_files', stats.get('indexed', 0))}")
    console.print(f"  Total chunks: {stats.get('total_chunks', 0)}")
    
    if stats.get("errors"):
        console.print(f"\n[yellow]Errors ({len(stats['errors'])}):[/yellow]")
        for error in stats["errors"][:5]:
            console.print(f"  - {error}")


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", "--host", "-h"),
    port: int = typer.Option(8000, "--port", "-p"),
    reload: bool = typer.Option(False, "--reload", "-r"),
):
    """Start the API server"""
    import uvicorn
    
    console.print(f"\n[bold]Starting ReadMatrix server[/bold]")
    console.print(f"  URL: http://{host}:{port}")
    console.print(f"  Docs: http://{host}:{port}/docs\n")
    
    uvicorn.run(
        "readmatrix.main:app",
        host=host,
        port=port,
        reload=reload,
    )


@app.command()
def stats():
    """Show index statistics"""
    from .indexer import IndexManager
    
    manager = IndexManager()
    stats = manager.get_stats()
    
    console.print("\n[bold]Index Statistics[/bold]\n")
    
    table = Table(show_header=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value")
    
    table.add_row("Total Files", str(stats["total_files"]))
    table.add_row("Total Chunks", str(stats["total_chunks"]))
    table.add_row("Books", str(len(stats.get("book_ids", []))))
    
    if stats.get("files"):
        for status, count in stats["files"].items():
            table.add_row(f"  {status}", str(count))
    
    console.print(table)


@app.command()
def eval(
    cases: Path = typer.Option(Path("eval_cases.jsonl"), "--cases", help="评测样例文件"),
    top_k: int = typer.Option(5, "--top-k", help="每条样例的检索数量"),
    mode: str = typer.Option("retrieval", "--mode", "-m", help="模式: retrieval | generation"),
    limit: int = typer.Option(0, "--limit", "-n", help="限制测试数量（0为不限制）"),
):
    """运行离线 RAG 评测"""
    from .eval import run as run_eval

    run_eval(cases=cases, top_k=top_k, mode=mode, limit=limit)


if __name__ == "__main__":
    app()
