import os

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client")

import pytest

from app import create_app
from app.routes_tasks import clean


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_health(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.get_json() == {"status": "ok"}


def test_tasks_require_login(client):
    assert client.get("/api/tasks").status_code == 401
    assert client.post("/api/tasks", json={"title": "x"}).status_code == 401


def test_bad_token_rejected(client):
    res = client.get("/api/auth/me", headers={"Authorization": "Bearer nope"})
    assert res.status_code == 401


def test_google_login_needs_credential(client):
    assert client.post("/api/auth/google", json={}).status_code == 400


def test_clean_requires_title():
    with pytest.raises(ValueError):
        clean({"title": "   "})


def test_clean_validates_fields():
    out = clean({"title": " Ship it ", "priority": "high", "due_date": "2026-10-31", "description": " hi "})
    assert out == {"title": "Ship it", "priority": "high", "due_date": "2026-10-31", "description": "hi"}
    with pytest.raises(ValueError):
        clean({"title": "a", "priority": "urgent"})
    with pytest.raises(ValueError):
        clean({"title": "a", "due_date": "tomorrow"})
    with pytest.raises(ValueError):
        clean({"title": "a", "status": "done"})


def test_partial_update_does_not_require_title():
    assert clean({"status": "completed"}, partial=True) == {"status": "completed"}
