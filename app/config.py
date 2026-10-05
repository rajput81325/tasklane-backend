import os
from dotenv import load_dotenv

load_dotenv(override=True)


def _split(value: str) -> list[str]:
    return [v.strip().rstrip("/") for v in value.split(",") if v.strip()]


class Config:
    SECRET_KEY = os.getenv("JWT_SECRET", "dev-secret-change-me")
    JWT_EXPIRES_HOURS = int(os.getenv("JWT_EXPIRES_HOURS", "168"))

    SUPABASE_URL = os.getenv("SUPABASE_URL", "")
    SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")

    FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173").rstrip("/")
    CORS_ORIGINS = _split(os.getenv("CORS_ORIGINS", FRONTEND_URL))

    EMAIL_ENABLED = os.getenv("EMAIL_ENABLED", "true").lower() == "true"
    GMAIL_CLIENT_ID = os.getenv("GMAIL_CLIENT_ID", "") or GOOGLE_CLIENT_ID
    GMAIL_CLIENT_SECRET = os.getenv("GMAIL_CLIENT_SECRET", "")
    GMAIL_REFRESH_TOKEN = os.getenv("GMAIL_REFRESH_TOKEN", "")
    GMAIL_SENDER = os.getenv("GMAIL_SENDER", "")
