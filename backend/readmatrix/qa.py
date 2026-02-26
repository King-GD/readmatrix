"""QA Engine - RAG pipeline with grounded citations and conversation memory"""

from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Optional

from .config import get_settings
from .conversation import ContextAssembler, ConversationMessage, ConversationService
from .models import Citation
from .retriever import Retriever


QA_PROMPT = """你是一位深度阅读助手，帮助用户基于他们的读书笔记回答问题。

【你的任务】
1. 先理解用户问题的核心意图
2. 分析提供的笔记内容，找出与问题相关的关键信息
3. 结合会话上下文，将多条观点进行整合、对比、归纳
4. 给出有深度、有结构的回答

【笔记使用比例】
请将笔记内容的占比控制在约 {note_ratio}%。
- 0%：完全基于你的理解回答
- 100%：严格只使用笔记内容

【回答要求】
1. 不要简单罗列笔记内容，要进行深度分析和整合
2. 对话中出现代词（他/它/这/那）且指代不清时，先提出澄清问题
3. 使用 [1][2] 等标记引用来源，引用必须出现在正文中
4. 可以补充你的理解，但要与笔记观点一致，不得编造
5. 回答要有结构：先给出核心观点，再展开分析
6. 当占比 > 0 且笔记中没有相关信息时，回答"根据你的笔记，我没有找到相关信息。"

【会话摘要】
{conversation_summary}

【最近对话】
{recent_dialogue}

【用户的笔记】
{note_context}

【当前问题】
{question}

【回答】"""


AMBIGUOUS_REFERENCES = (
    "他",
    "她",
    "它",
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


@dataclass
class PreparedContext:
    """预处理后的上下文，供 ask/ask_stream 共用。"""

    prompt: str
    citations: list[Citation]
    has_chunks: bool
    note_context: str


@dataclass
class AskResult:
    """会话问答结果，覆盖普通回答与澄清场景。"""

    answer: str
    citations: list[Citation]
    conversation_id: str
    needs_clarification: bool = False
    clarification_question: str | None = None


class QAEngine:
    """Question-answering engine with grounded citations"""

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
        """Lazy-load LLM client based on provider"""
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
        """根据配置生成提示词。"""
        safe_ratio = max(0, min(100, note_ratio))
        return QA_PROMPT.format(
            question=question,
            note_ratio=safe_ratio,
            conversation_summary=conversation_summary,
            recent_dialogue=recent_dialogue,
            note_context=note_context,
        )

    def _rewrite_query(self, original_query: str) -> list[str]:
        """
        将用户问题改写为更适合检索的查询。
        返回 2-3 个更具体的搜索查询，提高检索召回率。
        """
        settings = get_settings()

        prompt = f"""将以下问题改写为 2-3 个更具体的搜索查询，用于在读书笔记中检索相关内容。

要求：
1. 提取问题中的核心概念和关键词
2. 考虑同义词和相关表达
3. 每行输出一个查询，不要编号

问题：{original_query}

搜索查询："""

        try:
            response = self.client.chat.completions.create(
                model=settings.llm_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=200,
            )

            queries = response.choices[0].message.content.strip().split("\n")
            queries = [q.strip().lstrip("0123456789.-、) ") for q in queries if q.strip()]
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
        """
        统一的上下文准备逻辑：查询改写 + 检索 + 组装上下文 + 构建 Prompt。
        """
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
        )

    def _contains_ambiguous_reference(self, query: str) -> bool:
        """判断问题中是否包含潜在指代词。"""
        text = query.strip()
        if not text:
            return False
        return any(token in text for token in AMBIGUOUS_REFERENCES)

    def _has_explicit_subject(self, query: str) -> bool:
        """判断问题是否显式给出了主语，避免误触发澄清。"""
        text = query.strip()
        if any(token in text for token in EXPLICIT_SUBJECT_HINTS):
            return True

        # 若包含中文引号或英文引号中的实体，认为主语较明确
        if "“" in text and "”" in text:
            return True
        if '"' in text:
            return True

        # 句长较长且包含明显描述词时，通常信息已足够
        return len(text) >= 20

    def _rule_based_clarification(
        self,
        query: str,
        recent_messages: list[ConversationMessage],
    ) -> bool:
        """基于规则判断是否需要澄清。"""
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
        """使用小模型判定是否应先澄清，失败时回退规则结果。"""
        settings = get_settings()
        history_lines = []
        for item in recent_messages[-6:]:
            role = "用户" if item.role == "user" else "助手"
            history_lines.append(f"{role}: {item.content}")
        history_text = "\n".join(history_lines) or "（无历史）"

        prompt = f"""你是对话澄清分类器。

任务：判断“当前问题”在“历史对话”下是否指代不清，是否需要先追问澄清。
输出要求：仅输出 YES 或 NO。

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
        """组合规则与模型判定，决定是否进入澄清流程。"""
        if not self._rule_based_clarification(query, recent_messages):
            return False
        return self._llm_based_clarification(query, recent_messages)

    def _build_clarification_question(
        self,
        query: str,
        recent_messages: list[ConversationMessage],
    ) -> str:
        """构建澄清追问语句。"""
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
        """基于最近对话生成摘要，失败时返回旧摘要。"""
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
        """调用模型生成完整回答。"""
        settings = get_settings()
        response = self.client.chat.completions.create(
            model=settings.llm_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=settings.temperature,
        )
        return response.choices[0].message.content or ""

    def ask(
        self,
        query: str,
        book_id: Optional[str] = None,
        book_title: Optional[str] = None,
    ) -> tuple[str, list[Citation]]:
        """保留旧接口：单轮问答。"""
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
    ) -> AskResult:
        """会话问答入口：支持混合记忆与澄清。"""
        settings = get_settings()
        conv_id = self.conversation_service.ensure_conversation(conversation_id)

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
        )

    async def ask_stream(
        self,
        query: str,
        book_id: Optional[str] = None,
        book_title: Optional[str] = None,
    ) -> AsyncIterator[dict]:
        """保留旧接口：单轮流式问答。"""
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
    ) -> AsyncIterator[dict]:
        """会话流式问答入口：新增 meta 事件并支持澄清流程。"""
        settings = get_settings()
        conv_id = self.conversation_service.ensure_conversation(conversation_id)

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
