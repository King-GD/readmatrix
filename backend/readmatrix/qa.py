"""QA Engine - RAG pipeline with grounded citations and conversation memory."""

from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Optional

from .config import get_settings
from .conversation import (
    ContextAssembler,
    ConversationMessage,
    ConversationService,
    DebateState,
)
from .models import Citation
from .retriever import Retriever


QA_PROMPT = """你是一位深度阅读助手，帮助用户基于他们的读书笔记回答问题。

【你的任务】
1. 理解用户问题的核心意图。
2. 分析笔记中与问题相关的关键信息。
3. 结合会话上下文，完成对比、整合与归纳。
4. 给出有结构、可解释的回答。

【笔记使用比例】
请将笔记内容占比控制在约 {note_ratio}% 。

【回答要求】
1. 不要简单罗列笔记内容，要做分析和整合。
2. 对话中出现“它/这/那”等指代不清时，先提出澄清问题。
3. 使用 [1][2] 等引用标记，并确保出现在正文里。
4. 可补充你的理解，但不得编造与笔记冲突的事实。
5. 当占比 > 0 且笔记无相关信息时，回答“根据你的笔记，我没有找到相关信息。”

【会话摘要】
{conversation_summary}

【最近对话】
{recent_dialogue}

【用户笔记】
{note_context}

【当前问题】
{question}

【回答】"""

AMBIGUOUS_REFERENCES = (
    "它",
    "他",
    "她",
    "这",
    "那",
    "这个",
    "那个",
    "这件事",
    "那件事",
    "这种",
    "这样",
    "上面",
    "前面",
    "刚才",
    "之前",
    "前者",
    "后者",
)

EXPLICIT_SUBJECT_HINTS = (
    "这本书",
    "那本书",
    "这个问题",
    "这个回答",
    "上一个回答",
)

DEBATE_END_COMMANDS = ("结束", "结束辩论", "停止辩论")

DEBATE_PROMPT = """你正在与用户进行读书辩论，请你明确站在用户立场的对立面进行回应。

【辩题】
{topic}

【用户立场】
{user_stance}

【你的立场要求】
你必须站在用户立场的对立面，给出有证据支持的反驳或补充观点。

【证据规则】
1. 优先使用用户笔记中的证据，并在正文中使用 [1][2] 这类引用编号。
2. 允许补充通用知识；凡是非笔记内容，必须在对应句末添加【非笔记依据】。
3. 不允许把通用知识伪装成笔记证据。
4. 回答末尾必须增加“非笔记依据”小节，列出本次使用的非笔记依据要点；若没有则写“无”。

【输出风格】
1. 逻辑清晰、语气克制，不做人身攻击。
2. 先给核心反驳观点，再给展开论证。
3. 尽量结合会话历史避免重复。

【会话摘要】
{conversation_summary}

【最近对话】
{recent_dialogue}

【用户笔记】
{note_context}

【用户本轮发言】
{question}

【回答】"""

DEBATE_SUMMARY_PROMPT = """你是这场读书辩论的主持人。请根据辩论记录输出总结。

【辩题】
{topic}

【用户立场】
{user_stance}

【是否判胜负】
{judge_mode}

【辩论记录】
{history}

【输出要求】
1. 默认输出中立总结。
2. 如果“是否判胜负”为 winner，则增加“胜负判断”小节，给出胜方和理由。
3. 总结必须包含以下小节：
   - 双方核心论点
   - 共识与分歧
   - 证据质量点评（区分笔记依据与非笔记依据）
   - 下一步可验证问题
4. 不要编造不存在的论点或证据。
"""


@dataclass
class PreparedContext:
    """Preprocessed context shared by ask/ask_stream flows."""

    prompt: str
    citations: list[Citation]
    has_chunks: bool
    note_context: str
    conversation_summary: str
    recent_dialogue: str


@dataclass
class AskResult:
    """Conversation ask result for normal and clarification/debate cases."""

    answer: str
    citations: list[Citation]
    conversation_id: str
    needs_clarification: bool = False
    clarification_question: str | None = None
    mode: str = "qa"
    debate_status: str | None = None
    debate_event: str | None = None


class QAEngine:
    """Question-answering engine with grounded citations."""

    def __init__(
        self,
        retriever: Retriever | None = None,
        conversation_service: ConversationService | None = None,
        context_assembler: ContextAssembler | None = None,
    ):
        self.retriever = retriever or Retriever()
        self.conversation_service = conversation_service or ConversationService()
        self.context_assembler = context_assembler or ContextAssembler()
        self._client = None

    @property
    def client(self):
        """Lazy-load LLM client based on provider."""
        if self._client is None:
            import openai

            settings = get_settings()
            if settings.llm_provider == "siliconflow":
                self._client = openai.OpenAI(
                    api_key=settings.siliconflow_api_key,
                    base_url=settings.siliconflow_base_url,
                )
            else:
                self._client = openai.OpenAI(api_key=settings.openai_api_key)
        return self._client

    def _build_prompt(
        self,
        *,
        question: str,
        note_ratio: int,
        conversation_summary: str,
        recent_dialogue: str,
        note_context: str,
    ) -> str:
        """Build QA prompt with runtime sections."""
        safe_ratio = max(0, min(100, note_ratio))
        return QA_PROMPT.format(
            question=question,
            note_ratio=safe_ratio,
            conversation_summary=conversation_summary,
            recent_dialogue=recent_dialogue,
            note_context=note_context,
        )

    def _rewrite_query(self, original_query: str) -> list[str]:
        """Rewrite user question into 2-3 retrieval-friendly queries."""
        settings = get_settings()
        prompt = f"""将以下问题改写为 2-3 个更具体的搜索查询，用于在读书笔记中检索相关内容。

要求：
1. 提取核心概念和关键词
2. 覆盖常见同义表达
3. 每行一个查询，不要编号

问题：{original_query}

搜索查询："""

        try:
            response = self.client.chat.completions.create(
                model=settings.llm_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=200,
            )
            text = response.choices[0].message.content or ""
            queries = [q.strip().lstrip("0123456789.-、 ") for q in text.split("\n") if q.strip()]
            if original_query not in queries:
                queries.insert(0, original_query)
            return queries[:3]
        except Exception:
            return [original_query]

    def _prepare_context(
        self,
        query: str,
        book_id: Optional[str] = None,
        book_title: Optional[str] = None,
        summary: str = "",
        recent_messages: list[ConversationMessage] | None = None,
    ) -> PreparedContext:
        """Prepare retrieval context, citations, and final QA prompt."""
        settings = get_settings()
        queries = self._rewrite_query(query)

        all_chunks = []
        seen_chunk_ids = set()

        for q in queries:
            chunks = self.retriever.search(
                query=q,
                top_k=settings.retrieval_top_k,
                book_id=book_id,
                book_title=book_title,
            )
            for chunk in chunks:
                if chunk.chunk_id not in seen_chunk_ids:
                    seen_chunk_ids.add(chunk.chunk_id)
                    all_chunks.append(chunk)

        chunks = all_chunks[: settings.retrieval_top_k]

        context_parts = []
        citations: list[Citation] = []
        for i, chunk in enumerate(chunks, 1):
            citation = Citation.from_chunk(chunk, i)
            citations.append(citation)

            chapter = " / ".join(chunk.title_path) if chunk.title_path else ""
            header = f"[{i}] {chunk.book_title}"
            if chapter:
                header += f" / {chapter}"
            context_parts.append(f"{header}\n{chunk.content}")

        note_context = "\n\n".join(context_parts)
        sections = self.context_assembler.assemble(
            summary=summary,
            recent_messages=recent_messages or [],
            retrieved_context=note_context,
        )

        prompt = self._build_prompt(
            question=query,
            note_ratio=settings.qa_note_ratio,
            conversation_summary=sections["conversation_summary"],
            recent_dialogue=sections["recent_dialogue"],
            note_context=sections["note_context"],
        )

        return PreparedContext(
            prompt=prompt,
            citations=citations,
            has_chunks=bool(chunks),
            note_context=note_context,
            conversation_summary=sections["conversation_summary"],
            recent_dialogue=sections["recent_dialogue"],
        )

    def _contains_ambiguous_reference(self, query: str) -> bool:
        text = query.strip()
        if not text:
            return False
        return any(token in text for token in AMBIGUOUS_REFERENCES)

    def _has_explicit_subject(self, query: str) -> bool:
        text = query.strip()
        if any(token in text for token in EXPLICIT_SUBJECT_HINTS):
            return True
        if "“" in text and "”" in text:
            return True
        if '"' in text:
            return True
        return len(text) >= 20

    def _rule_based_clarification(
        self,
        query: str,
        recent_messages: list[ConversationMessage],
    ) -> bool:
        if not self._contains_ambiguous_reference(query):
            return False
        if self._has_explicit_subject(query):
            return False
        if not recent_messages:
            return True
        return True

    def _llm_based_clarification(
        self,
        query: str,
        recent_messages: list[ConversationMessage],
    ) -> bool:
        settings = get_settings()
        history_lines = []
        for item in recent_messages[-6:]:
            role = "用户" if item.role == "user" else "助手"
            history_lines.append(f"{role}: {item.content}")
        history_text = "\n".join(history_lines) or "（无历史）"

        prompt = f"""你是对话澄清分类器。

任务：判断“当前问题”在“历史对话”下是否指代不清、是否需要先追问澄清。
只输出 YES 或 NO。

历史对话：
{history_text}

当前问题：
{query}
"""

        try:
            response = self.client.chat.completions.create(
                model=settings.llm_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=5,
            )
            answer = (response.choices[0].message.content or "").strip().upper()
            return answer.startswith("YES")
        except Exception:
            return self._rule_based_clarification(query, recent_messages)

    def _needs_clarification(
        self,
        query: str,
        recent_messages: list[ConversationMessage],
    ) -> bool:
        if not self._rule_based_clarification(query, recent_messages):
            return False
        return self._llm_based_clarification(query, recent_messages)

    def _build_clarification_question(
        self,
        query: str,
        recent_messages: list[ConversationMessage],
    ) -> str:
        if recent_messages:
            recent_hint = recent_messages[-1].content.strip().replace("\n", " ")[:48]
            if recent_hint:
                return (
                    "我需要先确认一下：你这次提到的对象具体指哪一个？"
                    f"例如你是指“{recent_hint}”里的哪部分？"
                )
        return "我需要先确认一下：你说的“它/这/那”具体指什么对象？请补充主语后我再继续回答。"

    def _build_summary_text(
        self,
        previous_summary: str,
        history: list[ConversationMessage],
    ) -> str:
        settings = get_settings()
        history_lines = []
        for item in history[-16:]:
            role = "用户" if item.role == "user" else "助手"
            history_lines.append(f"{role}: {item.content}")
        history_text = "\n".join(history_lines)

        prompt = f"""请把以下对话整理成紧凑摘要，供后续追问使用。

要求：
1. 保留用户目标、关键结论、关键术语
2. 保留已确认的约束与偏好
3. 不要虚构事实
4. 输出中文，最多 1200 字

历史摘要：
{previous_summary or '（无）'}

最近对话：
{history_text}

新摘要："""

        try:
            response = self.client.chat.completions.create(
                model=settings.llm_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=500,
            )
            text = (response.choices[0].message.content or "").strip()
            return text or previous_summary
        except Exception:
            return previous_summary

    def _call_llm_answer(self, prompt: str) -> str:
        settings = get_settings()
        response = self.client.chat.completions.create(
            model=settings.llm_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=settings.temperature,
        )
        return response.choices[0].message.content or ""

    def _is_debate_end_command(self, query: str) -> bool:
        return query.strip() in DEBATE_END_COMMANDS

    def _normalize_debate_config(self, debate: dict | None) -> dict:
        payload = debate or {}
        topic = str(payload.get("topic") or "").strip()
        user_stance = str(payload.get("user_stance") or "").strip()
        judge_mode = str(payload.get("judge_mode") or "none").strip().lower()
        if judge_mode not in {"none", "winner"}:
            judge_mode = "none"
        return {
            "topic": topic,
            "user_stance": user_stance,
            "judge_mode": judge_mode,
        }

    def _ensure_active_debate_state(self, conversation_id: str, debate: dict) -> dict | None:
        latest_state = self.conversation_service.get_latest_debate_state(conversation_id)
        changed = (
            not latest_state
            or latest_state.get("topic") != debate["topic"]
            or latest_state.get("user_stance") != debate["user_stance"]
            or latest_state.get("judge_mode") != debate["judge_mode"]
            or latest_state.get("status") != "active"
        )
        if changed:
            self.conversation_service.save_debate_state(
                conversation_id=conversation_id,
                state=DebateState(
                    topic=debate["topic"],
                    user_stance=debate["user_stance"],
                    judge_mode=debate["judge_mode"],
                    status="active",
                ),
            )
            latest_state = self.conversation_service.get_latest_debate_state(conversation_id)
        return latest_state

    def _build_debate_turn_prompt(self, query: str, debate: dict, ctx: PreparedContext) -> str:
        note_context = ctx.note_context.strip() if ctx.note_context else "（未检索到相关笔记片段）"
        return DEBATE_PROMPT.format(
            topic=debate["topic"],
            user_stance=debate["user_stance"],
            conversation_summary=ctx.conversation_summary,
            recent_dialogue=ctx.recent_dialogue,
            note_context=note_context,
            question=query,
        )

    def _collect_debate_history(
        self,
        conversation_id: str,
        state_created_at: str | None,
    ) -> list[ConversationMessage]:
        if state_created_at:
            return self.conversation_service.list_messages_since(
                conversation_id=conversation_id,
                since_created_at=state_created_at,
                limit=200,
                include_system=False,
            )
        return self.conversation_service.list_messages(
            conversation_id=conversation_id,
            limit=200,
            offset=0,
            include_system=False,
        )

    def _build_debate_summary_prompt(self, debate: dict, history: list[ConversationMessage]) -> str:
        history_lines: list[str] = []
        for item in history:
            if item.role not in {"user", "assistant"}:
                continue
            role = "用户" if item.role == "user" else "助手"
            text = item.content.strip()
            if not text:
                continue
            history_lines.append(f"{role}: {text}")

        history_text = "\n".join(history_lines) or "（无有效辩论记录）"
        return DEBATE_SUMMARY_PROMPT.format(
            topic=debate["topic"],
            user_stance=debate["user_stance"],
            judge_mode=debate["judge_mode"],
            history=history_text,
        )

    def _ensure_non_note_section(self, answer: str) -> str:
        """Ensure debate answer always contains a non-note evidence section."""
        text = answer.strip()
        if "非笔记依据" in text:
            return text
        return f"{text}\n\n非笔记依据：\n- 无"

    def ask(
        self,
        query: str,
        book_id: Optional[str] = None,
        book_title: Optional[str] = None,
    ) -> tuple[str, list[Citation]]:
        """Legacy single-turn entrypoint."""
        settings = get_settings()
        ctx = self._prepare_context(query, book_id, book_title)

        if not ctx.has_chunks and settings.qa_note_ratio > 0:
            return "根据你的笔记，我没有找到相关信息。", []

        answer = self._call_llm_answer(ctx.prompt)
        return answer, ctx.citations

    def ask_with_conversation(
        self,
        query: str,
        book_id: Optional[str] = None,
        book_title: Optional[str] = None,
        conversation_id: str | None = None,
        use_context: bool = True,
        mode: str = "qa",
        debate: dict | None = None,
    ) -> AskResult:
        """Conversation entrypoint for QA mode and debate mode."""
        settings = get_settings()
        conv_id = self.conversation_service.ensure_conversation(conversation_id)

        if mode == "debate":
            debate_cfg = self._normalize_debate_config(debate)
            if not debate_cfg["topic"] or not debate_cfg["user_stance"]:
                raise ValueError("debate topic and user_stance are required")

            active_state = self._ensure_active_debate_state(conv_id, debate_cfg)
            recent_before = (
                self.conversation_service.get_recent_window(conv_id) if use_context else []
            )
            self.conversation_service.append_user_message(conv_id, query)

            if self._is_debate_end_command(query):
                history = self._collect_debate_history(
                    conversation_id=conv_id,
                    state_created_at=(active_state or {}).get("created_at"),
                )
                summary_prompt = self._build_debate_summary_prompt(debate_cfg, history)
                answer = self._ensure_non_note_section(self._call_llm_answer(summary_prompt))
                self.conversation_service.append_assistant_message(
                    conv_id,
                    answer,
                    citations=[],
                    is_clarification=False,
                )
                self.conversation_service.save_debate_state(
                    conv_id,
                    DebateState(
                        topic=debate_cfg["topic"],
                        user_stance=debate_cfg["user_stance"],
                        judge_mode=debate_cfg["judge_mode"],
                        status="ended",
                    ),
                )
                self.conversation_service.refresh_summary_if_needed(
                    conv_id,
                    self._build_summary_text,
                )
                return AskResult(
                    answer=answer,
                    citations=[],
                    conversation_id=conv_id,
                    mode="debate",
                    debate_status="ended",
                    debate_event="end_summary",
                )

            summary = self.conversation_service.get_summary(conv_id) if use_context else ""
            ctx = self._prepare_context(
                query=query,
                book_id=book_id,
                book_title=book_title,
                summary=summary,
                recent_messages=recent_before if use_context else [],
            )
            debate_prompt = self._build_debate_turn_prompt(query, debate_cfg, ctx)
            answer = self._ensure_non_note_section(self._call_llm_answer(debate_prompt))
            response_citations = ctx.citations if ctx.has_chunks else []
            self.conversation_service.append_assistant_message(
                conv_id,
                answer,
                citations=[c.to_dict() for c in response_citations],
                is_clarification=False,
            )
            self.conversation_service.refresh_summary_if_needed(
                conv_id,
                self._build_summary_text,
            )
            return AskResult(
                answer=answer,
                citations=response_citations,
                conversation_id=conv_id,
                mode="debate",
                debate_status="active",
                debate_event="normal",
            )

        recent_before = (
            self.conversation_service.get_recent_window(conv_id) if use_context else []
        )
        self.conversation_service.append_user_message(conv_id, query)

        if use_context and self.conversation_service.get_recent_clarification_count(conv_id) < 2:
            if self._needs_clarification(query, recent_before):
                question = self._build_clarification_question(query, recent_before)
                self.conversation_service.append_assistant_message(
                    conv_id,
                    question,
                    citations=[],
                    is_clarification=True,
                )
                return AskResult(
                    answer=question,
                    citations=[],
                    conversation_id=conv_id,
                    needs_clarification=True,
                    clarification_question=question,
                    mode="qa",
                )

        summary = self.conversation_service.get_summary(conv_id) if use_context else ""
        ctx = self._prepare_context(
            query=query,
            book_id=book_id,
            book_title=book_title,
            summary=summary,
            recent_messages=recent_before if use_context else [],
        )

        if not ctx.has_chunks and settings.qa_note_ratio > 0:
            answer = "根据你的笔记，我没有找到相关信息。"
            self.conversation_service.append_assistant_message(conv_id, answer, citations=[])
            self.conversation_service.refresh_summary_if_needed(
                conv_id,
                self._build_summary_text,
            )
            return AskResult(
                answer=answer,
                citations=[],
                conversation_id=conv_id,
                mode="qa",
            )

        answer = self._call_llm_answer(ctx.prompt)
        self.conversation_service.append_assistant_message(
            conv_id,
            answer,
            citations=[c.to_dict() for c in ctx.citations],
            is_clarification=False,
        )
        self.conversation_service.refresh_summary_if_needed(
            conv_id,
            self._build_summary_text,
        )

        return AskResult(
            answer=answer,
            citations=ctx.citations,
            conversation_id=conv_id,
            mode="qa",
        )

    async def ask_stream(
        self,
        query: str,
        book_id: Optional[str] = None,
        book_title: Optional[str] = None,
    ) -> AsyncIterator[dict]:
        """Legacy streaming single-turn entrypoint."""
        settings = get_settings()
        ctx = self._prepare_context(query, book_id, book_title)

        if not ctx.has_chunks and settings.qa_note_ratio > 0:
            yield {
                "event": "delta",
                "data": {"content": "根据你的笔记，我没有找到相关信息。"},
            }
            yield {"event": "citations", "data": []}
            yield {"event": "done", "data": {}}
            return

        stream = self.client.chat.completions.create(
            model=settings.llm_model,
            messages=[{"role": "user", "content": ctx.prompt}],
            temperature=settings.temperature,
            stream=True,
        )

        for chunk in stream:
            if chunk.choices[0].delta.content:
                yield {
                    "event": "delta",
                    "data": {"content": chunk.choices[0].delta.content},
                }

        yield {"event": "citations", "data": [c.to_dict() for c in ctx.citations]}
        yield {"event": "done", "data": {}}

    async def ask_stream_with_conversation(
        self,
        query: str,
        book_id: Optional[str] = None,
        book_title: Optional[str] = None,
        conversation_id: str | None = None,
        use_context: bool = True,
        mode: str = "qa",
        debate: dict | None = None,
    ) -> AsyncIterator[dict]:
        """Streaming conversation entrypoint for QA mode and debate mode."""
        settings = get_settings()
        conv_id = self.conversation_service.ensure_conversation(conversation_id)

        if mode == "debate":
            debate_cfg = self._normalize_debate_config(debate)
            if not debate_cfg["topic"] or not debate_cfg["user_stance"]:
                raise ValueError("debate topic and user_stance are required")

            active_state = self._ensure_active_debate_state(conv_id, debate_cfg)
            recent_before = (
                self.conversation_service.get_recent_window(conv_id) if use_context else []
            )
            self.conversation_service.append_user_message(conv_id, query)

            if self._is_debate_end_command(query):
                history = self._collect_debate_history(
                    conversation_id=conv_id,
                    state_created_at=(active_state or {}).get("created_at"),
                )
                summary_prompt = self._build_debate_summary_prompt(debate_cfg, history)
                answer = self._ensure_non_note_section(self._call_llm_answer(summary_prompt))
                self.conversation_service.append_assistant_message(
                    conv_id,
                    answer,
                    citations=[],
                    is_clarification=False,
                )
                self.conversation_service.save_debate_state(
                    conv_id,
                    DebateState(
                        topic=debate_cfg["topic"],
                        user_stance=debate_cfg["user_stance"],
                        judge_mode=debate_cfg["judge_mode"],
                        status="ended",
                    ),
                )
                self.conversation_service.refresh_summary_if_needed(
                    conv_id,
                    self._build_summary_text,
                )

                yield {
                    "event": "meta",
                    "data": {
                        "conversation_id": conv_id,
                        "needs_clarification": False,
                        "clarification_question": None,
                        "mode": "debate",
                        "debate_status": "ended",
                        "debate_event": "end_summary",
                    },
                }
                yield {"event": "delta", "data": {"content": answer}}
                yield {"event": "citations", "data": []}
                yield {"event": "done", "data": {}}
                return

            summary = self.conversation_service.get_summary(conv_id) if use_context else ""
            ctx = self._prepare_context(
                query=query,
                book_id=book_id,
                book_title=book_title,
                summary=summary,
                recent_messages=recent_before if use_context else [],
            )
            debate_prompt = self._build_debate_turn_prompt(query, debate_cfg, ctx)

            yield {
                "event": "meta",
                "data": {
                    "conversation_id": conv_id,
                    "needs_clarification": False,
                    "clarification_question": None,
                    "mode": "debate",
                    "debate_status": "active",
                    "debate_event": "normal",
                },
            }

            stream = self.client.chat.completions.create(
                model=settings.llm_model,
                messages=[{"role": "user", "content": debate_prompt}],
                temperature=settings.temperature,
                stream=True,
            )

            answer_parts: list[str] = []
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    answer_parts.append(delta)
                    yield {"event": "delta", "data": {"content": delta}}

            full_answer = self._ensure_non_note_section("".join(answer_parts))
            response_citations = ctx.citations if ctx.has_chunks else []
            self.conversation_service.append_assistant_message(
                conv_id,
                full_answer,
                citations=[c.to_dict() for c in response_citations],
                is_clarification=False,
            )
            self.conversation_service.refresh_summary_if_needed(
                conv_id,
                self._build_summary_text,
            )

            yield {"event": "citations", "data": [c.to_dict() for c in response_citations]}
            yield {"event": "done", "data": {}}
            return

        recent_before = (
            self.conversation_service.get_recent_window(conv_id) if use_context else []
        )
        self.conversation_service.append_user_message(conv_id, query)

        if use_context and self.conversation_service.get_recent_clarification_count(conv_id) < 2:
            if self._needs_clarification(query, recent_before):
                question = self._build_clarification_question(query, recent_before)
                self.conversation_service.append_assistant_message(
                    conv_id,
                    question,
                    citations=[],
                    is_clarification=True,
                )
                yield {
                    "event": "meta",
                    "data": {
                        "conversation_id": conv_id,
                        "needs_clarification": True,
                        "clarification_question": question,
                        "mode": "qa",
                        "debate_status": None,
                        "debate_event": None,
                    },
                }
                yield {"event": "delta", "data": {"content": question}}
                yield {"event": "citations", "data": []}
                yield {"event": "done", "data": {}}
                return

        summary = self.conversation_service.get_summary(conv_id) if use_context else ""
        ctx = self._prepare_context(
            query=query,
            book_id=book_id,
            book_title=book_title,
            summary=summary,
            recent_messages=recent_before if use_context else [],
        )

        yield {
            "event": "meta",
            "data": {
                "conversation_id": conv_id,
                "needs_clarification": False,
                "clarification_question": None,
                "mode": "qa",
                "debate_status": None,
                "debate_event": None,
            },
        }

        if not ctx.has_chunks and settings.qa_note_ratio > 0:
            answer = "根据你的笔记，我没有找到相关信息。"
            self.conversation_service.append_assistant_message(conv_id, answer, citations=[])
            self.conversation_service.refresh_summary_if_needed(
                conv_id,
                self._build_summary_text,
            )
            yield {"event": "delta", "data": {"content": answer}}
            yield {"event": "citations", "data": []}
            yield {"event": "done", "data": {}}
            return

        stream = self.client.chat.completions.create(
            model=settings.llm_model,
            messages=[{"role": "user", "content": ctx.prompt}],
            temperature=settings.temperature,
            stream=True,
        )

        answer_parts: list[str] = []
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                answer_parts.append(delta)
                yield {"event": "delta", "data": {"content": delta}}

        full_answer = "".join(answer_parts)
        self.conversation_service.append_assistant_message(
            conv_id,
            full_answer,
            citations=[c.to_dict() for c in ctx.citations],
            is_clarification=False,
        )
        self.conversation_service.refresh_summary_if_needed(
            conv_id,
            self._build_summary_text,
        )

        yield {"event": "citations", "data": [c.to_dict() for c in ctx.citations]}
        yield {"event": "done", "data": {}}
