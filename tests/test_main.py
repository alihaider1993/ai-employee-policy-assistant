from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
    
    
def test_ask_requires_question():
    response = client.post(
        "/ask",
        json={},
    )

    assert response.status_code == 422
    
    
def test_ask_returns_cached_answer():
    response = client.post(
        "/ask",
        json={
            "question": "Can I carry unused annual leave into the next year?"
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert "answer" in data
    assert len(data["answer"]) > 0