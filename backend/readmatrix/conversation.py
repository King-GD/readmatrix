"""会话管理与上下文组装服务。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .indexer.database import Database


@dataclass
class ConversationMessage:
    """会话消息模型，用于服务层与 API 层传递。"""

    id: str
    conversation_id: str
    role: str
    content: str
    citations: list[dict]
    created_at: str
    token_estimate: int
    is_clarification: bool = False
    is_summary: bool = False

    @classmethod
    def from_dict(cls, payload: dict) -> "ConversationMessage":
        """从数据库字典记录构建消息对象。"""
        return cls(
            id=payload["id"],
            conversation_id=payload["conversation_id"],
            role=payload["role"],
            content=payload["content"],
            citations=payload.get("citations", []),
            created_at=payload["created_at"],
            token_estimate=int(payload.get("token_estimate", 0)),
            is_clarification=bool(payload.get("is_clarification", False)),
            is_summary=bool(payload.get("is_summary", False)),
        )


class ConversationService:
    """会话服务，负责会话 CRUD、消息读写与摘要刷新触发。"""

    def __init__(
        self,
        db: Database | None = None,
        window_turns: int = 6,
        summary_refresh_every: int = 8,
        summary_max_chars: int = 1200,
    ):
        self.db = db or Database()
        self.window_turns = max(1, window_turns)
        self.summary_refresh_every = max(1, summary_refresh_every)
        self.summary_max_chars = max(200, summary_max_chars)

    def create_conversation(self, title: str | None = None) -> str:
        """创建新会话并返回会话 ID。"""
        return self.db.create_conversation(title=title)

    def ensure_conversation(self, conversation_id: str | None = None) -> str:
        """确保会话可用：不存在则自动创建新会话。"""
        if conversation_id and self.db.conversation_exists(conversation_id):
            return conversation_id
        return self.create_conversation()

    def delete_conversation(self, conversation_id: str):
        """删除会话及其消息。"""
        self.db.delete_conversation(conversation_id)

    def list_messages(
        self,
        conversation_id: str,
        limit: int = 30,
        offset: int = 0,
        include_system: bool = False,
    ) -> list[ConversationMessage]:
        """分页读取会话消息，默认不包含 system 摘要消息。"""
        records = self.db.list_conversation_messages(
            conversation_id=conversation_id,
            limit=limit,
            offset=offset,
            include_system=include_system,
        )
        return [ConversationMessage.from_dict(item) for item in records]

    def append_user_message(self, conversation_id: str, content: str) -> str:
        """追加用户消息并返回消息 ID。"""
        return self.db.add_conversation_message(
            conversation_id=conversation_id,
            role="user",
            content=content,
            citations=[],
            token_estimate=self._estimate_tokens(content),
        )

    def append_assistant_message(
        self,
        conversation_id: str,
        content: str,
        citations: list[dict] | None = None,
        is_clarification: bool = False,
    ) -> str:
        """追加助手消息并返回消息 ID。"""
        return self.db.add_conversation_message(
            conversation_id=conversation_id,
            role="assistant",
            content=content,
            citations=citations or [],
            token_estimate=self._estimate_tokens(content),
            is_clarification=is_clarification,
        )

    def get_recent_window(self, conversation_id: str) -> list[ConversationMessage]:
        """获取最近窗口消息（按轮次换算为消息条数）。"""
        limit = self.window_turns * 2
        records = self.db.get_recent_conversation_messages(
            conversation_id=conversation_id,
            limit=limit,
            include_system=False,
        )
        return [ConversationMessage.from_dict(item) for item in records]

    def get_summary(self, conversation_id: str) -> str:
        """读取会话摘要，不存在时返回空字符串。"""
        return self.db.get_latest_summary(conversation_id) or ""

    def save_summary(self, conversation_id: str, summary: str):
        """保存会话摘要，长度超过限制时自动截断。"""
        if not summary:
            return
        safe_summary = summary[: self.summary_max_chars]
        self.db.save_summary(conversation_id, safe_summary)

    def should_refresh_summary(self, conversation_id: str) -> bool:
        """根据用户轮次判断是否需要刷新摘要。"""
        user_count = self.db.count_conversation_messages(
            conversation_id=conversation_id,
            include_system=False,
            role="user",
        )
        return user_count > 0 and user_count % self.summary_refresh_every == 0

    def refresh_summary_if_needed(
        self,
        conversation_id: str,
        summary_builder: Callable[[str, list[ConversationMessage]], str],
    ) -> None:
        """满足阈值时刷新摘要，失败则静默降级。"""
        if not self.should_refresh_summary(conversation_id):
            return

        previous_summary = self.get_summary(conversation_id)
        history = self.list_messages(
            conversation_id=conversation_id,
            limit=self.window_turns * 4,
            offset=0,
            include_system=False,
        )
        if not history:
            return

        try:
            updated_summary = summary_builder(previous_summary, history)
        except Exception:
            return

        if updated_summary:
            self.save_summary(conversation_id, updated_summary)

    def get_recent_clarification_count(self, conversation_id: str, limit: int = 2) -> int:
        """读取最近连续澄清次数，避免无限澄清循环。"""
        return self.db.count_recent_clarifications(conversation_id=conversation_id, limit=limit)

    def _estimate_tokens(self, content: str) -> int:
        """粗略估算 token 数，便于后续做成本统计。"""
        return max(1, len(content) // 4)


class ContextAssembler:
    """上下文组装器，统一拼装摘要、最近对话与检索上下文。"""

    def __init__(self, summary_max_chars: int = 1200):
        self.summary_max_chars = max(200, summary_max_chars)

    def assemble(
        self,
        summary: str,
        recent_messages: list[ConversationMessage],
        retrieved_context: str,
    ) -> dict[str, str]:
        """输出结构化上下文片段，供 Prompt 模板直接注入。"""
        conversation_summary = summary.strip()[: self.summary_max_chars] if summary else ""
        recent_dialogue = self._format_recent_dialogue(recent_messages)
        note_context = retrieved_context.strip() if retrieved_context else ""

        return {
            "conversation_summary": conversation_summary or "（暂无会话摘要）",
            "recent_dialogue": recent_dialogue or "（暂无历史对话）",
            "note_context": note_context or "（未检索到相关笔记片段）",
        }

    def _format_recent_dialogue(self, messages: list[ConversationMessage]) -> str:
        """将最近消息格式化为可读对话文本。"""
        lines: list[str] = []
        for item in messages:
            if item.role == "user":
                prefix = "用户"
            elif item.role == "assistant":
                prefix = "助手"
            else:
                continue
            text = item.content.strip()
            if not text:
                continue
            lines.append(f"{prefix}: {text}")
        return "\n".join(lines)
