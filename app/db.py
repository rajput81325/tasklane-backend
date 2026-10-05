from flask import current_app
from supabase import Client, create_client

_client: Client | None = None


def get_db() -> Client:
    """Lazily create one Supabase client (service_role) per process."""
    global _client
    if _client is None:
        cfg = current_app.config
        if not cfg["SUPABASE_URL"] or not cfg["SUPABASE_SERVICE_ROLE_KEY"]:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
        _client = create_client(cfg["SUPABASE_URL"], cfg["SUPABASE_SERVICE_ROLE_KEY"])
    return _client
