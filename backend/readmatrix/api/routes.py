"""API routes - 4 core endpoints"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
import json

from ..config import get_settings
from ..indexer import IndexManager, VectorStore, Database
from ..retriever import Retriever
from ..qa import QAEngine


router = APIRouter(prefix="/api")


# === Request/Response Models ===

class AskRequest(BaseModel):
    query: str
    filters: Optional[dict] = None


class AskResponse(BaseModel):
    answer: str
    citations: list[dict]


class IndexRequest(BaseModel):
    full_rebuild: bool = False


class IndexResponse(BaseModel):
    status: str
    stats: dict


class DoctorResponse(BaseModel):
    status: str
    checks: list[dict]


# === Health Check ===

@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "ok", "version": "0.1.0"}


# === Doctor ===

@router.post("/doctor", response_model=DoctorResponse)
async def doctor():
    """
    Environment self-check with enhanced diagnostics.
    
    Checks:
    1. Vault path exists
    2. WeRead folder detected
    3. WeRead file structure valid
    4. SQLite writable
    5. ChromaDB persistent
    6. OpenAI API available
    """
    settings = get_settings()
    checks = []
    all_passed = True
    
    # 1. Vault path
    vault_exists = settings.vault_path.exists()
    checks.append({
        "name": "Vault Path",
        "passed": vault_exists,
        "message": str(settings.vault_path) if vault_exists else f"Not found: {settings.vault_path}",
    })
    if not vault_exists:
        all_passed = False
    
    # 2. WeRead folder
    weread_path = settings.weread_path
    weread_exists = weread_path.exists()
    md_count = len(list(weread_path.glob("*.md"))) if weread_exists else 0
    checks.append({
        "name": "WeRead Folder",
        "passed": weread_exists and md_count > 0,
        "message": f"Found {md_count} files" if weread_exists else f"Not found: {weread_path}",
    })
    if not weread_exists:
        all_passed = False
    
    # 3. WeRead structure detection
    weread_valid = False
    if weread_exists and md_count > 0:
        sample_file = next(weread_path.glob("*.md"), None)
        if sample_file:
            try:
                content = sample_file.read_text(encoding="utf-8")[:1000]
                weread_valid = "bookId:" in content or "📌" in content
            except Exception:
                pass
    checks.append({
        "name": "WeRead Structure",
        "passed": weread_valid,
        "message": "Valid WeRead format detected" if weread_valid else "No valid WeRead files found",
    })
    
    # 4. SQLite writable
    sqlite_ok = False
    try:
        db = Database()
        db.get_file_count()  # Simple read test
        sqlite_ok = True
    except Exception as e:
        sqlite_ok = False
    checks.append({
        "name": "SQLite Database",
        "passed": sqlite_ok,
        "message": str(settings.sqlite_path) if sqlite_ok else "Cannot access database",
    })
    if not sqlite_ok:
        all_passed = False
    
    # 5. ChromaDB persistent
    chroma_ok = False
    try:
        vs = VectorStore()
        chroma_ok = vs.test_persistence()
    except Exception:
        chroma_ok = False
    checks.append({
        "name": "ChromaDB Storage",
        "passed": chroma_ok,
        "message": str(settings.chroma_path) if chroma_ok else "Cannot persist data",
    })
    if not chroma_ok:
        all_passed = False
    
    # 6. OpenAI API
    openai_ok = False
    if settings.openai_api_key:
        try:
            import openai
            client = openai.OpenAI(api_key=settings.openai_api_key)
            # Simple test - list models
            client.models.list()
            openai_ok = True
        except Exception:
            openai_ok = False
    checks.append({
        "name": "OpenAI API",
        "passed": openai_ok,
        "message": "Connected" if openai_ok else "API key missing or invalid",
    })
    if not openai_ok:
        all_passed = False
    
    return DoctorResponse(
        status="ok" if all_passed else "error",
        checks=checks,
    )


# === Index ===

@router.post("/index", response_model=IndexResponse)
async def index(request: IndexRequest):
    """
    Build or rebuild the index.
    
    Args:
        full_rebuild: If true, clear and rebuild from scratch
    """
    try:
        manager = IndexManager()
        
        if request.full_rebuild:
            stats = manager.full_rebuild()
        else:
            stats = manager.incremental_update()
        
        return IndexResponse(
            status="ok",
            stats=stats,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# === Ask ===

@router.post("/ask")
async def ask(request: AskRequest, req: Request):
    """
    Ask a question with grounded answer.
    
    Supports SSE streaming via Accept: text/event-stream header.
    
    Request body:
        query: Question to ask
        filters: Optional {"book_id": "...", "book_title": "..."}
    
    Response (JSON):
        answer: Generated answer with [1] [2] citations
        citations: List of citation objects
    
    Response (SSE):
        event: delta - {"content": "..."}
        event: citations - [...]
        event: done - {}
    """
    filters = request.filters or {}
    book_id = filters.get("book_id")
    book_title = filters.get("book_title")
    
    # Check if SSE requested
    accept = req.headers.get("accept", "")
    if "text/event-stream" in accept:
        return StreamingResponse(
            _stream_answer(request.query, book_id, book_title),
            media_type="text/event-stream",
        )
    
    # Regular JSON response
    try:
        qa = QAEngine()
        answer, citations = qa.ask(
            query=request.query,
            book_id=book_id,
            book_title=book_title,
        )
        
        return AskResponse(
            answer=answer,
            citations=[c.to_dict() for c in citations],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def _stream_answer(query: str, book_id: str | None, book_title: str | None):
    """Generate SSE events for streaming answer"""
    qa = QAEngine()
    
    async for event in qa.ask_stream(query, book_id, book_title):
        event_type = event["event"]
        data = json.dumps(event["data"], ensure_ascii=False)
        yield f"event: {event_type}\ndata: {data}\n\n"
