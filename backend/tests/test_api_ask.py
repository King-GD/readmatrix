"""API 问答接口兼容性测试。"""

from fastapi.testclient import TestClient

from readmatrix.main import app
from readmatrix.qa import AskResult, QAEngine


client = TestClient(app)


def test_ask_backward_compatible(monkeypatch):
    """验证旧请求体（仅 query/filters）仍可调用 /api/ask。"""

    def fake_ask_with_conversation(
        self,
        query: str,
        book_id=None,
        book_title=None,
        conversation_id=None,
        use_context=True,
    ):
        return AskResult(
            answer=f"echo:{query}",
            citations=[],
            conversation_id=conversation_id or "conv_test",
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
