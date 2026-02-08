"""QA Engine - RAG pipeline with grounded citations"""

from dataclasses import dataclass
from typing import AsyncIterator, Optional

from .config import get_settings
from .models import Chunk, Citation
from .retriever import Retriever


QA_PROMPT = """你是一位深度阅读助手，帮助用户基于他们的读书笔记回答问题。

【你的任务】
1. 先理解用户问题的核心意图
2. 分析提供的笔记内容，找出与问题相关的关键信息
3. 将多条笔记的观点进行整合、对比、归纳
4. 给出有深度、有结构的回答

【笔记使用比例】
请将笔记内容的占比控制在约 {note_ratio}%。
- 0%：完全基于你的理解回答
- 100%：严格只使用笔记内容

【回答要求】
1. 不要简单罗列笔记内容，要进行深度分析和整合
2. 如果多条笔记讨论同一主题，要归纳共同点和差异
3. 使用 [1][2] 等标记引用来源，引用必须出现在正文中
4. 可以补充你的理解，但要与笔记观点一致，不得编造
5. 回答要有结构：先给出核心观点，再展开分析
6. 当占比 > 0 且笔记中没有相关信息时，回答"根据你的笔记，我没有找到相关信息。"

【格式要求】
请使用 Markdown 格式输出，提升可读性：
- 用 **加粗** 强调关键概念和核心观点
- 用分段组织内容，每段聚焦一个要点，段落间空一行
- 当有多个并列观点时，使用无序列表（- ）或有序列表（1. ）
- 保持简洁，避免冗长的段落

【用户的笔记】
{context}

【用户问题】
{question}

【回答】"""


@dataclass
class PreparedContext:
    """预处理后的上下文，供 ask/ask_stream 共用"""
    prompt: str
    citations: list[Citation]
    has_chunks: bool


class QAEngine:
    """Question-answering engine with grounded citations"""

    def __init__(self, retriever: Retriever | None = None):
        self.retriever = retriever or Retriever()
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

    def _build_prompt(self, context: str, question: str, note_ratio: int) -> str:
        """根据配置生成提示词。"""
        safe_ratio = max(0, min(100, note_ratio))
        return QA_PROMPT.format(
            context=context,
            question=question,
            note_ratio=safe_ratio,
        )

    def _rewrite_query(self, original_query: str) -> list[str]:
        """
        将用户问题改写为更适合检索的查询。
        返回2-3个更具体的搜索查询，提高检索召回率。
        """
        settings = get_settings()

        prompt = f"""将以下问题改写为2-3个更具体的搜索查询，用于在读书笔记中检索相关内容。

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
            # 过滤空行，保留有效查询
            queries = [q.strip().lstrip("0123456789.-、) ") for q in queries if q.strip()]
            # 始终包含原始查询
            if original_query not in queries:
                queries.insert(0, original_query)
            return queries[:3]  # 最多返回3个查询
        except Exception:
            # 如果改写失败，返回原始查询
            return [original_query]

    def _prepare_context(
        self,
        query: str,
        book_id: Optional[str] = None,
        book_title: Optional[str] = None,
    ) -> PreparedContext:
        """
        统一的上下文准备逻辑：查询改写 + 检索 + 构建 Prompt + 生成 Citations。
        供 ask() 和 ask_stream() 共用。
        """
        settings = get_settings()

        # 1. 查询改写：生成多个搜索查询
        queries = self._rewrite_query(query)

        # 2. 对每个查询进行检索，合并结果
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

        # 限制总数量
        chunks = all_chunks[:settings.retrieval_top_k]

        if not chunks:
            # 无检索结果时的 prompt
            prompt = self._build_prompt(
                context="",
                question=query,
                note_ratio=settings.qa_note_ratio,
            )
            return PreparedContext(prompt=prompt, citations=[], has_chunks=False)

        # 2. 构建上下文和引用
        context_parts = []
        citations = []

        for i, chunk in enumerate(chunks, 1):
            citation = Citation.from_chunk(chunk, i)
            citations.append(citation)

            chapter = " / ".join(chunk.title_path) if chunk.title_path else ""
            header = f"[{i}] {chunk.book_title}"
            if chapter:
                header += f" / {chapter}"

            context_parts.append(f"{header}\n{chunk.content}")

        context = "\n\n".join(context_parts)

        # 3. 生成 Prompt
        prompt = self._build_prompt(
            context=context,
            question=query,
            note_ratio=settings.qa_note_ratio,
        )

        return PreparedContext(prompt=prompt, citations=citations, has_chunks=True)

    
    def ask(
        self,
        query: str,
        book_id: Optional[str] = None,
        book_title: Optional[str] = None,
    ) -> tuple[str, list[Citation]]:
        """
        Ask a question and get a grounded answer.

        Args:
            query: User's question
            book_id: Filter to specific book
            book_title: Filter to specific book (fallback)

        Returns:
            Tuple of (answer, citations)
        """
        settings = get_settings()
        ctx = self._prepare_context(query, book_id, book_title)

        # 无检索结果且不允许纯模型回答
        if not ctx.has_chunks and settings.qa_note_ratio > 0:
            return "根据你的笔记，我没有找到相关信息。", []

        # 调用 LLM 生成回答
        response = self.client.chat.completions.create(
            model=settings.llm_model,
            messages=[{"role": "user", "content": ctx.prompt}],
            temperature=settings.temperature,
        )

        answer = response.choices[0].message.content
        return answer, ctx.citations

    async def ask_stream(
        self,
        query: str,
        book_id: Optional[str] = None,
        book_title: Optional[str] = None,
    ) -> AsyncIterator[dict]:
        """
        Stream answer with SSE events.

        Yields:
            {"event": "delta", "data": {"content": "..."}}
            {"event": "citations", "data": [...]}
            {"event": "done", "data": {}}
        """
        settings = get_settings()
        ctx = self._prepare_context(query, book_id, book_title)

        # 无检索结果且不允许纯模型回答
        if not ctx.has_chunks and settings.qa_note_ratio > 0:
            yield {"event": "delta", "data": {"content": "根据你的笔记，我没有找到相关信息。"}}
            yield {"event": "citations", "data": []}
            yield {"event": "done", "data": {}}
            return

        # 流式调用 LLM
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
                    "data": {"content": chunk.choices[0].delta.content}
                }

        yield {"event": "citations", "data": [c.to_dict() for c in ctx.citations]}
        yield {"event": "done", "data": {}}
