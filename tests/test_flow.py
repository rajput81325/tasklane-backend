"""End-to-end API flow against an in-memory fake of the Supabase client."""
import os
import uuid

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client")

import pytest

from app import create_app, emailer
from app.auth import issue_token


class Result:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, store, name):
        self.store, self.name = store, name
        self.filters, self.op, self.payload, self.cols = [], "select", None, "*"
        self.sort = None
        self.max = None

    def select(self, cols="*"):
        self.cols = cols
        return self

    def eq(self, k, v):
        self.filters.append(lambda r: r.get(k) == v)
        return self

    def or_(self, expr):
        pairs = [p.split(".eq.") for p in expr.split(",")]
        self.filters.append(lambda r: any(r.get(k) == v for k, v in pairs))
        return self

    def ilike(self, k, pattern):
        needle = pattern.strip("%").lower()
        self.filters.append(lambda r: needle in (r.get(k) or "").lower())
        return self

    def order(self, k, desc=False):
        self.sort = (k, desc)
        return self

    def limit(self, n):
        self.max = n
        return self

    def insert(self, row):
        self.op, self.payload = "insert", row
        return self

    def update(self, row):
        self.op, self.payload = "update", row
        return self

    def delete(self):
        self.op = "delete"
        return self

    def _embed(self, row):
        row = dict(row)
        users = {u["id"]: u for u in self.store["users"]}
        if self.name == "tasks" and "creator:" in self.cols:
            row["creator"], row["assignee"] = users[row["created_by"]], users[row["assigned_to"]]
        if self.name == "task_comments" and "author:" in self.cols:
            row["author"] = users[row["user_id"]]
        return row

    def execute(self):
        rows = self.store[self.name]
        match = [r for r in rows if all(f(r) for f in self.filters)]
        if self.op == "insert":
            row = {"id": str(uuid.uuid4()), "status": "todo", "priority": "medium", "description": "",
                   "created_at": f"2026-01-01T00:00:{len(rows):02d}", "completed_at": None, **self.payload}
            rows.append(row)
            return Result([row])
        if self.op == "update":
            for r in match:
                r.update(self.payload)
            return Result(match)
        if self.op == "delete":
            for r in match:
                rows.remove(r)
            return Result([])
        if self.sort:
            match.sort(key=lambda r: r[self.sort[0]], reverse=self.sort[1])
        if self.max:
            match = match[: self.max]
        return Result([self._embed(r) for r in match])


class FakeDB:
    def __init__(self):
        self.store = {"users": [], "tasks": [], "task_comments": [], "email_logs": []}

    def table(self, name):
        return FakeQuery(self.store, name)


@pytest.fixture()
def env(monkeypatch):
    app = create_app()
    app.config["TESTING"] = True
    db = FakeDB()
    for mod in ("app.auth", "app.routes_auth", "app.routes_tasks", "app.emailer"):
        monkeypatch.setattr(f"{mod}.get_db", lambda db=db: db)

    sent = []
    monkeypatch.setattr(emailer, "_queue", lambda to, event, subject, html, text, task_id: sent.append((to, event)))

    users = {}
    for key in ("alice", "bob", "carol"):
        u = {"id": str(uuid.uuid4()), "name": key.title(), "email": f"{key}@example.com", "avatar_url": None}
        db.store["users"].append(u)
        users[key] = u
    with app.app_context():
        headers = {k: {"Authorization": f"Bearer {issue_token(u)}"} for k, u in users.items()}
    return app.test_client(), users, headers, sent


def test_full_task_lifecycle(env):
    client, users, h, sent = env
    alice, bob = users["alice"], users["bob"]

    # create + assign -> assignee and creator are emailed
    res = client.post("/api/tasks", headers=h["alice"], json={"title": "Write report", "assigned_to": bob["id"], "priority": "high"})
    assert res.status_code == 201
    task = res.get_json()
    assert task["assignee"]["name"] == "Bob"
    assert sorted(sent) == sorted([(bob["email"], "task_assigned"), (alice["email"], "task_created")])

    # scopes
    assert len(client.get("/api/tasks?scope=assigned", headers=h["bob"]).get_json()) == 1
    assert len(client.get("/api/tasks?scope=assigned", headers=h["alice"]).get_json()) == 0
    assert len(client.get("/api/tasks?scope=created", headers=h["alice"]).get_json()) == 1
    assert len(client.get("/api/tasks?q=report", headers=h["bob"]).get_json()) == 1
    assert len(client.get("/api/tasks?q=nothing", headers=h["bob"]).get_json()) == 0

    # outsider cannot see or touch it
    assert client.get(f"/api/tasks/{task['id']}", headers=h["carol"]).status_code == 403
    assert client.patch(f"/api/tasks/{task['id']}", headers=h["carol"], json={"status": "completed"}).status_code == 403

    # assignee may change status but not details
    assert client.patch(f"/api/tasks/{task['id']}", headers=h["bob"], json={"title": "Hacked"}).status_code == 403
    sent.clear()
    res = client.patch(f"/api/tasks/{task['id']}", headers=h["bob"], json={"status": "completed"})
    assert res.status_code == 200 and res.get_json()["completed_at"]
    assert sorted(sent) == sorted([(alice["email"], "task_completed"), (bob["email"], "task_completed")])

    # completing again does not re-send
    sent.clear()
    client.patch(f"/api/tasks/{task['id']}", headers=h["bob"], json={"status": "completed"})
    assert sent == []

    # comments
    res = client.post(f"/api/tasks/{task['id']}/comments", headers=h["bob"], json={"body": "Done!"})
    assert res.status_code == 201
    detail = client.get(f"/api/tasks/{task['id']}", headers=h["alice"]).get_json()
    assert detail["comments"][0]["body"] == "Done!"

    stats = client.get("/api/stats", headers=h["alice"]).get_json()
    assert stats["total"] == 1 and stats["completed"] == 1

    # only the creator can delete
    assert client.delete(f"/api/tasks/{task['id']}", headers=h["bob"]).status_code == 403
    assert client.delete(f"/api/tasks/{task['id']}", headers=h["alice"]).status_code == 204
    assert client.get(f"/api/tasks/{task['id']}", headers=h["alice"]).status_code == 404


def test_self_assigned_gets_single_email_and_reassign_notifies(env):
    client, users, h, sent = env
    res = client.post("/api/tasks", headers=h["alice"], json={"title": "Solo"})
    task = res.get_json()
    assert task["assignee"]["id"] == users["alice"]["id"]
    assert sent == [(users["alice"]["email"], "task_created")]

    sent.clear()
    res = client.patch(f"/api/tasks/{task['id']}", headers=h["alice"], json={"assigned_to": users["carol"]["id"]})
    assert res.status_code == 200
    assert sent == [(users["carol"]["email"], "task_reassigned")]


def test_validation_errors(env):
    client, users, h, _ = env
    assert client.post("/api/tasks", headers=h["alice"], json={"title": ""}).status_code == 400
    assert client.post("/api/tasks", headers=h["alice"], json={"title": "x", "assigned_to": str(uuid.uuid4())}).status_code == 404


def test_email_renders(env):
    client, users, h, _ = env
    app = client.application
    task = {
        "id": "t1", "title": "Fix <b>bug</b>", "description": "Details", "priority": "high", "due_date": None,
        "creator": users["alice"], "assignee": users["bob"],
    }
    with app.app_context():
        html, text = emailer._render(task, "Task completed", "Bob marked this task as completed.")
    assert "Fix &lt;b&gt;bug&lt;/b&gt;" in html  # user input is escaped
    assert "?task=t1" in text and "Priority: High" in text
