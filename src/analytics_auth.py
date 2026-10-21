"""
analytics_auth.py
Separate OAuth flow for the YouTube Analytics API -- needs its own scope
(yt-analytics.readonly), different from both the upload-only token
(youtube.upload) and the live-streaming token (youtube) built earlier.
None of your existing tokens will work here; this needs its own
token file, generated once via the interactive browser flow.
"""
import pickle
import sys
from pathlib import Path

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

ANALYTICS_SCOPES = ["https://www.googleapis.com/auth/yt-analytics.readonly"]


def get_analytics_service(token_path: str, client_secret_path: str = None):
    """Loads/refreshes/creates a token scoped for read-only Analytics
    access. Same fall-through-to-interactive-login pattern as
    upload_youtube.get_authenticated_service() -- a revoked token falls
    through to a fresh browser login instead of crashing."""
    token_path = Path(token_path)
    creds = None

    if token_path.exists():
        with open(token_path, "rb") as f:
            creds = pickle.load(f)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                print(f"WARNING: stored analytics token could not be "
                      f"refreshed ({e}); falling back to interactive login.")
                creds = None
        if not creds:
            if not sys.stdin.isatty():
                raise RuntimeError(
                    f"No valid analytics token at {token_path} and this is an "
                    f"unattended run, so a browser login would hang. Authorize "
                    f"once from a terminal: python3 -m src.analytics_auth "
                    f"<channel_id>"
                )
            if not client_secret_path:
                raise RuntimeError(
                    f"No valid analytics token at {token_path} and no "
                    f"client_secret provided for interactive login. Run "
                    f"this once locally with a browser available."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                client_secret_path, ANALYTICS_SCOPES
            )
            creds = flow.run_local_server(port=0)

        token_path.parent.mkdir(parents=True, exist_ok=True)
        with open(token_path, "wb") as f:
            pickle.dump(creds, f)

    return build("youtubeAnalytics", "v2", credentials=creds)


if __name__ == "__main__":
    # One-time interactive authorization:  python3 -m src.analytics_auth cosmic_curious
    if len(sys.argv) < 2:
        print("usage: python3 -m src.analytics_auth <channel_id>")
        sys.exit(1)
    root = Path(__file__).resolve().parents[1]
    secret = root / "client_secret.json"
    svc = get_analytics_service(
        str(root / "tokens" / f"{sys.argv[1]}_analytics_token.pickle"),
        str(secret) if secret.exists() else None,
    )
    print("Analytics token ready:", svc is not None)
