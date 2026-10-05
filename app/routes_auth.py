import datetime as dt

from flask import Blueprint, current_app, g, jsonify, request
from google.auth.transport import requests as g_requests
from google.oauth2 import id_token

from .auth import issue_token, login_required
from .db import get_db

bp = Blueprint("auth", __name__)

PUBLIC_COLS = "id,name,email,avatar_url"


def public_user(u: dict) -> dict:
    return {k: u.get(k) for k in ("id", "name", "email", "avatar_url")}


@bp.post("/auth/google")
def google_login():
    """Exchange a Google ID token (from Google Identity Services) for an app session."""
    credential = (request.get_json(silent=True) or {}).get("credential")
    if not credential:
        return jsonify(error="Missing Google credential."), 400

    try:
        info = id_token.verify_oauth2_token(
            credential,
            g_requests.Request(),
            current_app.config["GOOGLE_CLIENT_ID"],
            clock_skew_in_seconds=10,
        )
    except ValueError:
        return jsonify(error="Google sign-in could not be verified. Please try again."), 401

    if not info.get("email_verified"):
        return jsonify(error="Your Google email address is not verified."), 401

    email = info["email"].lower()
    fields = {
        "google_id": info["sub"],
        "email": email,
        "name": info.get("name") or email.split("@")[0],
        "avatar_url": info.get("picture"),
        "last_login_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }

    db = get_db()
    existing = db.table("users").select("id").eq("email", email).limit(1).execute().data
    if existing:
        user = db.table("users").update(fields).eq("id", existing[0]["id"]).execute().data[0]
    else:
        user = db.table("users").insert(fields).execute().data[0]

    return jsonify(token=issue_token(user), user=public_user(user))


@bp.get("/auth/me")
@login_required
def me():
    return jsonify(public_user(g.user))


@bp.get("/users")
@login_required
def list_users():
    """Everyone who has signed in at least once; used for the assignee picker."""
    rows = get_db().table("users").select(PUBLIC_COLS).order("name").execute().data
    return jsonify(rows)
