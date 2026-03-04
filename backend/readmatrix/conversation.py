"""Conversation management and context assembly services."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

from .indexer.database import Database


DEBATE_STATE_PREFIX = "__debate_state__:"


@dataclass
class ConversationMessage:
    """Conversation message model used between service and API layers."""

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
        """Build a message object from database payload."""
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


@dataclass
class DebateState:
    """Debate runtime state persisted as hidden system metadata."""

    topic: str
    user_stance: str
    judge_mode: str = "none"
    status: str = "active"

    def to_dict(self) -> dict:
        return {
            "topic": self.topic,
            "user_stance": self.user_stance,
            "judge_mode": self.judge_mode,
            "status": self.status,
        }


class ConversationService:
    """Conversation service for CRUD, message IO, and summary refresh."""

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

    def list_conversations(
        self,
        limit: int = 30,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """List all conversations ordered by last activity."""
        return self.db.list_conversations(limit=limit, offset=offset)

    def create_conversation(self, title: str | None = None) -> str:
        """Create and return a new conversation ID."""
        return self.db.create_conversation(title=title)

    def ensure_conversation(self, conversation_id: str | None = None) -> str:
        """Ensure conversation is usable; create one when absent."""
        if conversation_id and self.db.conversation_exists(conversation_id):
            return conversation_id
        return self.create_conversation()

    def delete_conversation(self, conversation_id: str):
        """Delete conversation and all its messages."""
        self.db.delete_conversation(conversation_id)

    def list_messages(
        self,
        conversation_id: str,
        limit: int = 30,
        offset: int = 0,
        include_system: bool = False,
    ) -> list[ConversationMessage]:
        """Read conversation messages in ascending order."""
        records = self.db.list_conversation_messages(
            conversation_id=conversation_id,
            limit=limit,
            offset=offset,
            include_system=include_system,
        )
        return [ConversationMessage.from_dict(item) for item in records]

    def list_messages_since(
        self,
        conversation_id: str,
        since_created_at: str,
        limit: int = 200,
        include_system: bool = False,
    ) -> list[ConversationMessage]:
        """Read conversation messages since a timestamp."""
        records = self.db.list_conversation_messages_since(
            conversation_id=conversation_id,
            since_created_at=since_created_at,
            limit=limit,
            include_system=include_system,
        )
        return [ConversationMessage.from_dict(item) for item in records]

    def get_latest_debate_state(self, conversation_id: str) -> dict | None:
        """Read latest hidden debate state metadata from system message."""
        payload = self.db.get_latest_system_message_with_prefix(
            conversation_id=conversation_id,
            prefix=DEBATE_STATE_PREFIX,
        )
        if not payload:
            return None

        content = payload.get("content", "")
        if not isinstance(content, str) or not content.startswith(DEBATE_STATE_PREFIX):
            return None

        raw_json = content[len(DEBATE_STATE_PREFIX) :]
        try:
            state = json.loads(raw_json)
        except json.JSONDecodeError:
            return None

        if not isinstance(state, dict):
            return None

        state["created_at"] = payload.get("created_at")
        return state

    def save_debate_state(self, conversation_id: str, state: DebateState):
        """Persist hidden debate state metadata into system messages."""
        content = f"{DEBATE_STATE_PREFIX}{json.dumps(state.to_dict(), ensure_ascii=False)}"
        self.db.add_conversation_message(
            conversation_id=conversation_id,
            role="system",
            content=content,
            citations=[],
            token_estimate=self._estimate_tokens(content),
            is_summary=False,
        )

    def append_user_message(self, conversation_id: str, content: str) -> str:
        """Append a user message and return message ID."""
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
        """Append an assistant message and return message ID."""
        return self.db.add_conversation_message(
            conversation_id=conversation_id,
            role="assistant",
            content=content,
            citations=citations or [],
            token_estimate=self._estimate_tokens(content),
            is_clarification=is_clarification,
        )

    def get_recent_window(self, conversation_id: str) -> list[ConversationMessage]:
        """Read latest message window by turns."""
        limit = self.window_turns * 2
        records = self.db.get_recent_conversation_messages(
            conversation_id=conversation_id,
            limit=limit,
            include_system=False,
        )
        return [ConversationMessage.from_dict(item) for item in records]

    def get_summary(self, conversation_id: str) -> str:
        """Read latest summary text."""
        return self.db.get_latest_summary(conversation_id) or ""

    def save_summary(self, conversation_id: str, summary: str):
        """Save summary text with truncation."""
        if not summary:
            return
        safe_summary = summary[: self.summary_max_chars]
        self.db.save_summary(conversation_id, safe_summary)

    def should_refresh_summary(self, conversation_id: str) -> bool:
        """Decide whether summary should be refreshed by user turn count."""
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
        """Refresh summary when threshold is reached; degrade silently on failure."""
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
        """Count recent consecutive clarification replies."""
        return self.db.count_recent_clarifications(conversation_id=conversation_id, limit=limit)

    def _estimate_tokens(self, content: str) -> int:
        """Rough token estimate for future cost tracking."""
        return max(1, len(content) // 4)


class ContextAssembler:
    """Assemble summary, recent dialogue, and retrieved note context."""

    def __init__(self, summary_max_chars: int = 1200):
        self.summary_max_chars = max(200, summary_max_chars)

    def assemble(
        self,
        summary: str,
        recent_messages: list[ConversationMessage],
        retrieved_context: str,
    ) -> dict[str, str]:
        """Build structured context sections for prompt injection."""
        conversation_summary = summary.strip()[: self.summary_max_chars] if summary else ""
        recent_dialogue = self._format_recent_dialogue(recent_messages)
        note_context = retrieved_context.strip() if retrieved_context else ""

        return {
            "conversation_summary": conversation_summary or "（暂无会话摘要）",
            "recent_dialogue": recent_dialogue or "（暂无历史对话）",
            "note_context": note_context or "（未检索到相关笔记片段）",
        }

    def _format_recent_dialogue(self, messages: list[ConversationMessage]) -> str:
        """Format recent messages into readable dialogue text."""
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
