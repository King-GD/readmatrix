"""会话服务与上下文组装测试。"""

from pathlib import Path

from readmatrix.conversation import ContextAssembler, ConversationMessage, ConversationService
from readmatrix.indexer.database import Database


def test_conversation_service_crud(tmp_path: Path):
    """验证会话创建、写入、读取和删除。"""
    db = Database(db_path=tmp_path / "conversation.db")
    service = ConversationService(db=db, window_turns=2, summary_refresh_every=2)

    conversation_id = service.create_conversation(title="测试会话")
    assert conversation_id

    service.append_user_message(conversation_id, "乔布斯怎么看产品设计？")
    service.append_assistant_message(
        conversation_id,
        "他强调端到端体验。",
        citations=[{"id": 1}],
    )

    messages = service.list_messages(conversation_id=conversation_id, limit=10)
    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[1].role == "assistant"
    assert messages[1].citations == [{"id": 1}]

    service.save_summary(conversation_id, "用户关注产品设计与体验。")
    summary = service.get_summary(conversation_id)
    assert "产品设计" in summary

    service.delete_conversation(conversation_id)
    assert service.db.conversation_exists(conversation_id) is False


def test_context_assembler_sections():
    """验证上下文组装器输出结构化上下文。"""
    assembler = ContextAssembler(summary_max_chars=200)
    messages = [
        ConversationMessage(
            id="1",
            conversation_id="c1",
            role="user",
            content="乔布斯怎么看设计？",
            citations=[],
            created_at="2026-01-01T00:00:00",
            token_estimate=3,
        ),
        ConversationMessage(
            id="2",
            conversation_id="c1",
            role="assistant",
            content="他强调软硬件一体化。",
            citations=[],
            created_at="2026-01-01T00:00:01",
            token_estimate=4,
        ),
    ]

    sections = assembler.assemble(
        summary="用户偏好关注产品设计决策。",
        recent_messages=messages,
        retrieved_context="[1] 史蒂夫·乔布斯传 / 设计哲学",
    )

    assert "产品设计" in sections["conversation_summary"]
    assert "用户:" in sections["recent_dialogue"]
    assert "[1]" in sections["note_context"]
