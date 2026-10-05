"""Notification emails sent through the Gmail API.

Why the Gmail API (HTTPS) and not SMTP: free tiers on Render/Railway block outbound
SMTP ports, while HTTPS to gmail.googleapis.com always works.

Emails are sent on a background thread so API responses stay fast, and every attempt
is written to the `email_logs` table (sent / failed / skipped) for debugging.
"""
import base64
import logging
import threading
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape

import requests
from flask import current_app

from .db import get_db

log = logging.getLogger(__name__)

TOKEN_URL = "https://oauth2.googleapis.com/token"
SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"


# ------------------------------------------------------------------ transport
def _access_token(cfg) -> str:
    resp = requests.post(
        TOKEN_URL,
        data={
            "client_id": cfg["GMAIL_CLIENT_ID"],
            "client_secret": cfg["GMAIL_CLIENT_SECRET"],
            "refresh_token": cfg["GMAIL_REFRESH_TOKEN"],
            "grant_type": "refresh_token",
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _send_via_gmail(cfg, to: str, subject: str, html: str, text: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["To"] = to
    msg["From"] = f"Tasklane <{cfg['GMAIL_SENDER']}>"
    msg["Subject"] = subject
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

    resp = requests.post(
        SEND_URL,
        headers={"Authorization": f"Bearer {_access_token(cfg)}"},
        json={"raw": raw},
        timeout=15,
    )
    resp.raise_for_status()


def _queue(to: str, event: str, subject: str, html: str, text: str, task_id: str | None) -> None:
    app = current_app._get_current_object()

    def run():
        with app.app_context():
            cfg = app.config
            status, error = "sent", None
            if not cfg["EMAIL_ENABLED"] or not (
                cfg["GMAIL_CLIENT_ID"] and cfg["GMAIL_CLIENT_SECRET"] and cfg["GMAIL_REFRESH_TOKEN"] and cfg["GMAIL_SENDER"]
            ):
                status, error = "skipped", "Email disabled or Gmail credentials missing"
                log.warning("Email skipped for %s (%s)", to, event)
            else:
                try:
                    _send_via_gmail(cfg, to, subject, html, text)
                except Exception as exc:  # network, auth, quota...
                    status, error = "failed", str(exc)[:500]
                    log.exception("Email failed for %s (%s)", to, event)
            try:
                get_db().table("email_logs").insert(
                    {"task_id": task_id, "recipient": to, "event": event, "subject": subject, "status": status, "error": error}
                ).execute()
            except Exception:
                log.exception("Could not write email log")

    threading.Thread(target=run, daemon=True).start()


# ------------------------------------------------------------------- content
def _render(task: dict, heading: str, intro: str) -> tuple[str, str]:
    link = f"{current_app.config['FRONTEND_URL']}/?task={task['id']}"
    due = task.get("due_date") or "No due date"
    assignee = task["assignee"]["name"]
    rows = [("Task", task["title"]), ("Assigned to", assignee), ("Priority", task["priority"].capitalize()), ("Due", due)]

    table = "".join(
        f'<tr><td style="padding:6px 16px 6px 0;color:#667085">{escape(k)}</td>'
        f'<td style="padding:6px 0;color:#14181F"><strong>{escape(v)}</strong></td></tr>'
        for k, v in rows
    )
    desc = f'<p style="color:#475467;margin:16px 0">{escape(task["description"])}</p>' if task.get("description") else ""
    html = f"""<div style="font-family:Arial,Helvetica,sans-serif;max-width:520px;margin:0 auto;padding:24px">
  <h2 style="margin:0 0 8px;color:#14181F">{escape(heading)}</h2>
  <p style="margin:0 0 16px;color:#475467">{escape(intro)}</p>
  <table style="border-collapse:collapse;font-size:14px">{table}</table>{desc}
  <p style="margin:24px 0"><a href="{link}" style="background:#0F7B6C;color:#fff;padding:10px 18px;border-radius:6px;text-decoration:none">Open task</a></p>
  <p style="color:#98A2B3;font-size:12px">Sent by Tasklane</p>
</div>"""
    text = f"{heading}\n{intro}\n\n" + "\n".join(f"{k}: {v}" for k, v in rows) + f"\n\nOpen task: {link}\n"
    return html, text


def _send(person: dict, event: str, subject: str, heading: str, intro: str, task: dict) -> None:
    html, text = _render(task, heading, intro)
    _queue(person["email"], event, subject, html, text, task["id"])


# ---------------------------------------------------------------- public API
def notify_task_created(task: dict) -> None:
    creator, assignee, title = task["creator"], task["assignee"], task["title"]
    if creator["id"] == assignee["id"]:
        _send(creator, "task_created", f"Task created: {title}", "Task created", "You created a task for yourself.", task)
        return
    _send(
        assignee, "task_assigned", f"New task assigned to you: {title}", "You have a new task",
        f"{creator['name']} assigned this task to you.", task,
    )
    _send(
        creator, "task_created", f"Task created: {title}", "Task created",
        f"Your task was created and assigned to {assignee['name']}.", task,
    )


def notify_task_completed(task: dict, actor: dict) -> None:
    people = {task["creator"]["id"]: task["creator"], task["assignee"]["id"]: task["assignee"]}
    for person in people.values():
        _send(
            person, "task_completed", f"Task completed: {task['title']}", "Task completed",
            f"{actor['name']} marked this task as completed.", task,
        )


def notify_task_reassigned(task: dict, actor: dict) -> None:
    assignee = task["assignee"]
    if assignee["id"] == actor["id"]:
        return
    _send(
        assignee, "task_reassigned", f"Task assigned to you: {task['title']}", "A task was assigned to you",
        f"{actor['name']} assigned this task to you.", task,
    )
