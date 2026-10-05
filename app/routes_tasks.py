import datetime as dt

from flask import Blueprint, g, jsonify, request

from . import emailer
from .auth import login_required
from .db import get_db

bp = Blueprint("tasks", __name__)

STATUSES = {"todo", "in_progress", "completed"}
PRIORITIES = {"low", "medium", "high"}
USER_COLS = "id,name,email,avatar_url"
TASK_SELECT = (
    "*, "
    f"creator:users!tasks_created_by_fkey({USER_COLS}), "
    f"assignee:users!tasks_assigned_to_fkey({USER_COLS})"
)


def err(message: str, code: int = 400):
    return jsonify(error=message), code


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def clean(payload: dict, partial: bool = False) -> dict:
    """Validate and normalise task input. Raises ValueError with a user-facing message."""
    out: dict = {}

    if "title" in payload or not partial:
        title = (payload.get("title") or "").strip()
        if not title:
            raise ValueError("Give the task a title.")
        if len(title) > 200:
            raise ValueError("Title must be 200 characters or fewer.")
        out["title"] = title

    if "description" in payload:
        desc = (payload.get("description") or "").strip()
        if len(desc) > 2000:
            raise ValueError("Description must be 2000 characters or fewer.")
        out["description"] = desc

    if "priority" in payload:
        if payload["priority"] not in PRIORITIES:
            raise ValueError("Priority must be low, medium or high.")
        out["priority"] = payload["priority"]

    if "status" in payload:
        if payload["status"] not in STATUSES:
            raise ValueError("Status must be todo, in_progress or completed.")
        out["status"] = payload["status"]

    if "due_date" in payload:
        value = payload["due_date"]
        if not value:
            out["due_date"] = None
        else:
            try:
                out["due_date"] = dt.date.fromisoformat(str(value)).isoformat()
            except ValueError:
                raise ValueError("Due date must look like 2026-10-31.") from None

    if "assigned_to" in payload:
        out["assigned_to"] = payload["assigned_to"] or None

    return out


def fetch_task(task_id: str):
    try:
        rows = get_db().table("tasks").select(TASK_SELECT).eq("id", task_id).limit(1).execute().data
    except Exception:  # malformed uuid etc.
        return None
    return rows[0] if rows else None


def user_exists(user_id: str) -> bool:
    try:
        return bool(get_db().table("users").select("id").eq("id", user_id).limit(1).execute().data)
    except Exception:
        return False


def involved(task: dict, user_id: str) -> bool:
    return user_id in (task["created_by"], task["assigned_to"])


def involved_filter(user_id: str) -> str:
    return f"created_by.eq.{user_id},assigned_to.eq.{user_id}"


# ---------------------------------------------------------------- list / stats
@bp.get("/tasks")
@login_required
def list_tasks():
    uid = g.user["id"]
    scope = request.args.get("scope", "mine")
    status = request.args.get("status")
    priority = request.args.get("priority")
    q = (request.args.get("q") or "").strip()

    query = get_db().table("tasks").select(TASK_SELECT)
    if scope == "assigned":
        query = query.eq("assigned_to", uid)
    elif scope == "created":
        query = query.eq("created_by", uid)
    else:
        query = query.or_(involved_filter(uid))

    if status in STATUSES:
        query = query.eq("status", status)
    if priority in PRIORITIES:
        query = query.eq("priority", priority)
    if q:
        safe = q.replace("%", "").replace(",", " ")[:100]
        query = query.ilike("title", f"%{safe}%")

    rows = query.order("created_at", desc=True).execute().data
    return jsonify(rows)


@bp.get("/stats")
@login_required
def stats():
    uid = g.user["id"]
    rows = (
        get_db()
        .table("tasks")
        .select("status,due_date,assigned_to,created_by")
        .or_(involved_filter(uid))
        .execute()
        .data
    )
    today = dt.date.today().isoformat()
    open_rows = [r for r in rows if r["status"] != "completed"]
    return jsonify(
        total=len(rows),
        todo=sum(r["status"] == "todo" for r in rows),
        in_progress=sum(r["status"] == "in_progress" for r in rows),
        completed=sum(r["status"] == "completed" for r in rows),
        overdue=sum(1 for r in open_rows if r["due_date"] and r["due_date"] < today),
        open_for_me=sum(1 for r in open_rows if r["assigned_to"] == uid),
    )


# --------------------------------------------------------------------- create
@bp.post("/tasks")
@login_required
def create_task():
    try:
        data = clean(request.get_json(silent=True) or {})
    except ValueError as e:
        return err(str(e))

    assignee_id = data.get("assigned_to") or g.user["id"]
    if not user_exists(assignee_id):
        return err("That teammate could not be found.", 404)

    row = {**data, "assigned_to": assignee_id, "created_by": g.user["id"]}
    if row.get("status") == "completed":
        row["completed_at"] = now_iso()

    inserted = get_db().table("tasks").insert(row).execute().data[0]
    task = fetch_task(inserted["id"])
    emailer.notify_task_created(task)
    return jsonify(task), 201


# ------------------------------------------------------------- read / update
@bp.get("/tasks/<task_id>")
@login_required
def get_task(task_id):
    task = fetch_task(task_id)
    if not task:
        return err("Task not found.", 404)
    if not involved(task, g.user["id"]):
        return err("You don't have access to this task.", 403)

    comments = (
        get_db()
        .table("task_comments")
        .select("id,body,created_at,author:users(id,name,avatar_url)")
        .eq("task_id", task_id)
        .order("created_at")
        .execute()
        .data
    )
    return jsonify({**task, "comments": comments})


@bp.patch("/tasks/<task_id>")
@login_required
def update_task(task_id):
    task = fetch_task(task_id)
    if not task:
        return err("Task not found.", 404)

    uid = g.user["id"]
    is_creator = task["created_by"] == uid
    if not involved(task, uid):
        return err("You don't have access to this task.", 403)

    try:
        data = clean(request.get_json(silent=True) or {}, partial=True)
    except ValueError as e:
        return err(str(e))
    if not data:
        return err("Nothing to update.")

    if not is_creator and set(data) - {"status"}:
        return err("Only the person who created a task can edit its details. You can change its status.", 403)

    reassigned = False
    if "assigned_to" in data:
        if not data["assigned_to"]:
            return err("A task needs an assignee.")
        if not user_exists(data["assigned_to"]):
            return err("That teammate could not be found.", 404)
        reassigned = data["assigned_to"] != task["assigned_to"]

    completing = False
    if "status" in data and data["status"] != task["status"]:
        completing = data["status"] == "completed"
        data["completed_at"] = now_iso() if completing else None

    get_db().table("tasks").update(data).eq("id", task_id).execute()
    updated = fetch_task(task_id)

    if completing:
        emailer.notify_task_completed(updated, g.user)
    if reassigned:
        emailer.notify_task_reassigned(updated, g.user)
    return jsonify(updated)


@bp.delete("/tasks/<task_id>")
@login_required
def delete_task(task_id):
    task = fetch_task(task_id)
    if not task:
        return err("Task not found.", 404)
    if task["created_by"] != g.user["id"]:
        return err("Only the person who created a task can delete it.", 403)
    get_db().table("tasks").delete().eq("id", task_id).execute()
    return "", 204


# ------------------------------------------------------------------- comments
@bp.post("/tasks/<task_id>/comments")
@login_required
def add_comment(task_id):
    task = fetch_task(task_id)
    if not task:
        return err("Task not found.", 404)
    if not involved(task, g.user["id"]):
        return err("You don't have access to this task.", 403)

    body = ((request.get_json(silent=True) or {}).get("body") or "").strip()
    if not body:
        return err("Write a comment first.")
    if len(body) > 1000:
        return err("Comments must be 1000 characters or fewer.")

    inserted = (
        get_db().table("task_comments").insert({"task_id": task_id, "user_id": g.user["id"], "body": body}).execute().data[0]
    )
    return (
        jsonify(
            id=inserted["id"],
            body=inserted["body"],
            created_at=inserted["created_at"],
            author={"id": g.user["id"], "name": g.user["name"], "avatar_url": g.user.get("avatar_url")},
        ),
        201,
    )
