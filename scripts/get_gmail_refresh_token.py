"""One-time helper: create the Gmail refresh token used to send notification emails.

Prerequisites (see README, "Gmail setup"):
  1. In Google Cloud Console create an OAuth client of type "Desktop app".
  2. Enable the Gmail API for the project.
  3. pip install google-auth-oauthlib

Run:
  python scripts/get_gmail_refresh_token.py
Sign in with the Gmail account that should SEND the emails, then copy the printed
refresh token into GMAIL_REFRESH_TOKEN (and the client id/secret into GMAIL_CLIENT_ID/SECRET).
"""
import os

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

client_id = os.getenv("GMAIL_CLIENT_ID") or input("Desktop client ID: ").strip()
client_secret = os.getenv("GMAIL_CLIENT_SECRET") or input("Desktop client secret: ").strip()

flow = InstalledAppFlow.from_client_config(
    {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    },
    SCOPES,
)
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")

print("\nGMAIL_CLIENT_ID=" + client_id)
print("GMAIL_CLIENT_SECRET=" + client_secret)
print("GMAIL_REFRESH_TOKEN=" + str(creds.refresh_token))
