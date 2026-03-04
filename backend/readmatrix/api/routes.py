"""API routes for health, indexing, conversations, and ask."""

from typing import Literal, Optional
import json

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..conversation import ConversationService
from ..config import get_settings
from ..indexer import Database, IndexManager, VectorStore
from ..qa import QAEngine


router = APIRouter(prefix="/api")


# === Request/Response Models ===

class DebateRequest(BaseModel):
    topic: str
    user_stance: str
    judge_mode: Literal["none", "winner"] = "none"


class AskRequest(BaseModel):
    """问答请求模型。"""

    query: str
    filters: Optional[dict] = None
    conversation_id: Optional[str] = None
    use_context: bool = True
    mode: Literal["qa", "debate"] = "qa"
    debate: Optional[DebateRequest] = None


class AskResponse(BaseModel):
    """问答响应模型。"""

    answer: str
    citations: list[dict]
    conversation_id: str
    needs_clarification: bool = False
    clarification_question: Optional[str] = None
    mode: Literal["qa", "debate"] = "qa"
    debate_status: Optional[Literal["active", "ended"]] = None
    debate_event: Optional[Literal["normal", "end_summary"]] = None


class IndexRequest(BaseModel):
    full_rebuild: bool = False


class IndexResponse(BaseModel):
    status: str
    stats: dict


class DoctorResponse(BaseModel):
    status: str
    checks: list[dict]


class ConversationCreateRequest(BaseModel):
    """创建会话请求。"""

    title: Optional[str] = None


class ConversationCreateResponse(BaseModel):
    """创建会话响应。"""

    conversation_id: str


class ConversationMessagesResponse(BaseModel):
    """会话消息分页响应。"""

    conversation_id: str
    messages: list[dict]
    limit: int
    offset: int
    total: int
    debate_state: Optional[dict] = None


class GenericStatusResponse(BaseModel):
    """通用状态响应。"""

    status: str


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
    checks.append(
        {
            "name": "Vault Path",
            "passed": vault_exists,
            "message": str(settings.vault_path)
            if vault_exists
            else f"Not found: {settings.vault_path}",
        }
    )
    if not vault_exists:
        all_passed = False

    # 2. WeRead folder
    weread_path = settings.weread_path
    weread_exists = weread_path.exists()
    md_count = len(list(weread_path.glob("*.md"))) if weread_exists else 0
    checks.append(
        {
            "name": "WeRead Folder",
            "passed": weread_exists and md_count > 0,
            "message": f"Found {md_count} files"
            if weread_exists
            else f"Not found: {weread_path}",
        }
    )
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
    checks.append(
        {
            "name": "WeRead Structure",
            "passed": weread_valid,
            "message": "Valid WeRead format detected"
            if weread_valid
            else "No valid WeRead files found",
        }
    )

    # 4. SQLite writable
    sqlite_ok = False
    try:
        db = Database()
        db.get_file_count()  # Simple read test
        sqlite_ok = True
    except Exception:
        sqlite_ok = False
    checks.append(
        {
            "name": "SQLite Database",
            "passed": sqlite_ok,
            "message": str(settings.sqlite_path) if sqlite_ok else "Cannot access database",
        }
    )
    if not sqlite_ok:
        all_passed = False

    # 5. ChromaDB persistent
    chroma_ok = False
    try:
        vs = VectorStore()
        chroma_ok = vs.test_persistence()
    except Exception:
        chroma_ok = False
    checks.append(
        {
            "name": "ChromaDB Storage",
            "passed": chroma_ok,
            "message": str(settings.chroma_path) if chroma_ok else "Cannot persist data",
        }
    )
    if not chroma_ok:
        all_passed = False

    # 6. OpenAI API
    openai_ok = False
    if settings.openai_api_key:
        try:
            import openai

            client = openai.OpenAI(api_key=settings.openai_api_key)
            client.models.list()
            openai_ok = True
        except Exception:
            openai_ok = False
    checks.append(
        {
            "name": "OpenAI API",
            "passed": openai_ok,
            "message": "Connected" if openai_ok else "API key missing or invalid",
        }
    )
    if not openai_ok:
        all_passed = False

    return DoctorResponse(
        status="ok" if all_passed else "error",
        checks=checks,
    )


# === Conversations ===

@router.post("/conversations", response_model=ConversationCreateResponse)
async def create_conversation(request: ConversationCreateRequest | None = None):
    """创建新会话，返回会话 ID。"""
    service = ConversationService()
    title = request.title if request else None
    conversation_id = service.create_conversation(title=title)
    return ConversationCreateResponse(conversation_id=conversation_id)


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=ConversationMessagesResponse,
)
async def get_conversation_messages(
    conversation_id: str,
    limit: int = Query(30, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """分页读取会话消息（默认不返回 system 摘要消息）。"""
    service = ConversationService()
    if not service.db.conversation_exists(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = service.list_messages(
        conversation_id=conversation_id,
        limit=limit,
        offset=offset,
        include_system=False,
    )
    total = service.db.count_conversation_messages(
        conversation_id=conversation_id,
        include_system=False,
    )
    debate_state = service.get_latest_debate_state(conversation_id)

    return ConversationMessagesResponse(
        conversation_id=conversation_id,
        messages=[
            {
                "id": item.id,
                "role": item.role,
                "content": item.content,
                "citations": item.citations,
                "created_at": item.created_at,
                "is_clarification": item.is_clarification,
            }
            for item in messages
        ],
        limit=limit,
        offset=offset,
        total=total,
        debate_state=debate_state,
    )


@router.delete("/conversations/{conversation_id}", response_model=GenericStatusResponse)
async def delete_conversation(conversation_id: str):
    """删除会话及其历史消息。"""
    service = ConversationService()
    if not service.db.conversation_exists(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")

    service.delete_conversation(conversation_id)
    return GenericStatusResponse(status="ok")


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

@router.post("/ask", response_model=AskResponse)
async def ask(request: AskRequest, req: Request):
    """
    Ask a question with grounded answer and conversation memory.

    Supports SSE streaming via Accept: text/event-stream header.
    """
    filters = request.filters or {}
    book_id = filters.get("book_id")
    book_title = filters.get("book_title")
    mode = request.mode
    debate_payload = request.debate.model_dump() if request.debate else None

    if mode == "debate":
        if not debate_payload:
            raise HTTPException(
                status_code=400,
                detail="debate mode requires debate config",
            )
        topic = (debate_payload.get("topic") or "").strip()
        user_stance = (debate_payload.get("user_stance") or "").strip()
        if not topic or not user_stance:
            raise HTTPException(
                status_code=400,
                detail="debate topic and user_stance are required",
            )
        debate_payload["topic"] = topic
        debate_payload["user_stance"] = user_stance

    accept = req.headers.get("accept", "")
    if "text/event-stream" in accept:
        return StreamingResponse(
            _stream_answer(
                query=request.query,
                book_id=book_id,
                book_title=book_title,
                conversation_id=request.conversation_id,
                use_context=request.use_context,
                mode=mode,
                debate=debate_payload,
            ),
            media_type="text/event-stream",
        )

    try:
        qa = QAEngine()
        result = qa.ask_with_conversation(
            query=request.query,
            book_id=book_id,
            book_title=book_title,
            conversation_id=request.conversation_id,
            use_context=request.use_context,
            mode=mode,
            debate=debate_payload,
        )

        return AskResponse(
            answer=result.answer,
            citations=[c.to_dict() for c in result.citations],
            conversation_id=result.conversation_id,
            needs_clarification=result.needs_clarification,
            clarification_question=result.clarification_question,
            mode=result.mode,
            debate_status=result.debate_status,
            debate_event=result.debate_event,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def _stream_answer(
    query: str,
    book_id: str | None,
    book_title: str | None,
    conversation_id: str | None,
    use_context: bool,
    mode: str,
    debate: dict | None,
):
    """Generate SSE events for streaming answer with conversation metadata."""
    qa = QAEngine()

    async for event in qa.ask_stream_with_conversation(
        query=query,
        book_id=book_id,
        book_title=book_title,
        conversation_id=conversation_id,
        use_context=use_context,
        mode=mode,
        debate=debate,
    ):
        event_type = event["event"]
        data = json.dumps(event["data"], ensure_ascii=False)
        yield f"event: {event_type}\ndata: {data}\n\n"
