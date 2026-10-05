import datetime as dt
from functools import wraps

import jwt
from flask import current_app, g, jsonify, request

from .db import get_db


def issue_token(user: dict) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    payload = {
        "sub": user["id"],
        "email": user["email"],
        "iat": now,
        "exp": now + dt.timedelta(hours=current_app.config["JWT_EXPIRES_HOURS"]),
    }
    return jwt.encode(payload, current_app.config["SECRET_KEY"], algorithm="HS256")


def login_required(fn):
    """Require a valid Bearer token and load the user into flask.g.user."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return jsonify(error="Please sign in to continue."), 401
        try:
            data = jwt.decode(header[7:], current_app.config["SECRET_KEY"], algorithms=["HS256"])
        except jwt.PyJWTError:
            return jsonify(error="Your session has expired. Please sign in again."), 401

        rows = get_db().table("users").select("*").eq("id", data["sub"]).limit(1).execute().data
        if not rows:
            return jsonify(error="Account not found. Please sign in again."), 401
        g.user = rows[0]
        return fn(*args, **kwargs)

    return wrapper
