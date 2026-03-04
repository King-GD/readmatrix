"""Tests for /api/ask compatibility and debate mode validation."""

from fastapi.testclient import TestClient

from readmatrix.main import app
from readmatrix.qa import AskResult, QAEngine


client = TestClient(app)


def test_ask_backward_compatible(monkeypatch):
    """Legacy payload (query/filters only) should still work."""

    captured: dict = {}

    def fake_ask_with_conversation(
        self,
        query: str,
        book_id=None,
        book_title=None,
        conversation_id=None,
        use_context=True,
        mode="qa",
        debate=None,
    ):
        captured["mode"] = mode
        captured["debate"] = debate
        return AskResult(
            answer=f"echo:{query}",
            citations=[],
            conversation_id=conversation_id or "conv_test",
            mode=mode,
        )

    monkeypatch.setattr(QAEngine, "ask_with_conversation", fake_ask_with_conversation)

    resp = client.post(
        "/api/ask",
        json={
            "query": "测试问题",
            "filters": {},
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["answer"] == "echo:测试问题"
    assert data["conversation_id"] == "conv_test"
    assert data["citations"] == []
    assert data["mode"] == "qa"
    assert captured == {"mode": "qa", "debate": None}


def test_ask_debate_requires_config():
    """Debate mode requires debate config payload."""
    resp = client.post(
        "/api/ask",
        json={
            "query": "开始辩论",
            "mode": "debate",
        },
    )
    assert resp.status_code == 400
    assert "debate config" in resp.json()["detail"]


def test_ask_debate_requires_topic_and_stance():
    """Debate mode requires non-empty topic and user stance."""
    resp = client.post(
        "/api/ask",
        json={
            "query": "开始辩论",
            "mode": "debate",
            "debate": {
                "topic": " ",
                "user_stance": " ",
            },
        },
    )
    assert resp.status_code == 400
    assert "topic and user_stance" in resp.json()["detail"]


def test_ask_debate_passes_mode_and_payload(monkeypatch):
    """Debate mode payload should be passed to QA engine."""

    captured: dict = {}

    def fake_ask_with_conversation(
        self,
        query: str,
        book_id=None,
        book_title=None,
        conversation_id=None,
        use_context=True,
        mode="qa",
        debate=None,
    ):
        captured["mode"] = mode
        captured["debate"] = debate
        return AskResult(
            answer="debate-reply",
            citations=[],
            conversation_id=conversation_id or "conv_debate",
            mode="debate",
            debate_status="active",
            debate_event="normal",
        )

    monkeypatch.setattr(QAEngine, "ask_with_conversation", fake_ask_with_conversation)

    resp = client.post(
        "/api/ask",
        json={
            "query": "我的观点是阅读应该慢下来",
            "mode": "debate",
            "debate": {
                "topic": "深阅读是否过时",
                "user_stance": "深阅读不过时",
                "judge_mode": "none",
            },
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "debate"
    assert data["debate_status"] == "active"
    assert data["debate_event"] == "normal"
    assert captured["mode"] == "debate"
    assert captured["debate"] == {
        "topic": "深阅读是否过时",
        "user_stance": "深阅读不过时",
        "judge_mode": "none",
    }
