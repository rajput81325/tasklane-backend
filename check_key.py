import base64, json, os, requests
from dotenv import load_dotenv

load_dotenv(override=True)

url = os.getenv("SUPABASE_URL", "").rstrip("/")
key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

if key.startswith("sb_"):
    role = key.split("_")[1]
else:
    try:
        role = json.loads(base64.urlsafe_b64decode(key.split(".")[1] + "==")).get("role")
    except Exception:
        role = "unreadable"
print("key type:", role, "| length:", len(key))

h = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json", "Prefer": "return=minimal"}
r = requests.post(f"{url}/rest/v1/users", headers=h, json={"google_id": "diag", "email": "diag@example.com", "name": "diag"})
print("insert:", r.status_code, r.text[:150])
r = requests.delete(f"{url}/rest/v1/users?email=eq.diag@example.com", headers=h)
print("cleanup:", r.status_code)