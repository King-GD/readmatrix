"""Tests for the daily review API endpoint."""

from fastapi.testclient import TestClient

from readmatrix.main import app
from readmatrix.review import DailyReviewResult, ReviewService


client = TestClient(app)


def test_generate_daily_review_endpoint(monkeypatch):
    """The endpoint should return the generated conversation metadata."""

    def fake_generate_daily_review(self):
        return DailyReviewResult(
            conversation_id="review-conv",
            title="今日回顾 2026-03-08",
            status="ready",
            selected_chunk_id="chunk-1",
        )

    monkeypatch.setattr(ReviewService, "generate_daily_review", fake_generate_daily_review)

    response = client.post("/api/review/daily")

    assert response.status_code == 200
    assert response.json() == {
        "conversation_id": "review-conv",
        "title": "今日回顾 2026-03-08",
        "status": "ready",
    }
