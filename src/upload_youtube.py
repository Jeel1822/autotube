"""
upload_youtube.py
Uploads a finished video to YouTube using the free YouTube Data API v3.

Auth: uses OAuth2 with a stored refresh token (see README "YouTube API
setup" for the one-time process to get client_secret.json and a refresh
token per channel). This script never does the interactive browser login —
that only happens once, locally, when you generate the refresh token.
"""
import os
import pickle
from pathlib import Path

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def get_authenticated_service(token_path: str, client_secret_path: str = None):
    """
    Loads a saved token (refresh flow, non-interactive — used in CI).
    If no token exists yet, falls back to the interactive browser flow
    (only works locally, not in GitHub Actions).
    """
    creds = None
    token_path = Path(token_path)

    if token_path.exists():
        with open(token_path, "rb") as f:
            creds = pickle.load(f)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not client_secret_path:
                raise RuntimeError(
                    f"No valid token at {token_path} and no client_secret "
                    "provided for interactive login. Run this script locally "
                    "first to generate the token (see README)."
                )
            flow = InstalledAppFlow.from_client_secrets_file(client_secret_path, SCOPES)
            creds = flow.run_local_server(port=0)

        token_path.parent.mkdir(parents=True, exist_ok=True)
        with open(token_path, "wb") as f:
            pickle.dump(creds, f)

    return build("youtube", "v3", credentials=creds)


def upload_video(
    video_path: str,
    title: str,
    description: str,
    tags: list,
    category_id: str,
    token_path: str,
    client_secret_path: str = None,
    privacy_status: str = "public",
    is_short: bool = False,
    thumbnail_path: str = None,
) -> str:
    """Returns the uploaded video's YouTube ID."""
    youtube = get_authenticated_service(token_path, client_secret_path)

    # YouTube treats videos as Shorts automatically if they're vertical,
    # under 3 minutes, and the title/description mention #Shorts.
    if is_short and "#shorts" not in description.lower():
        description = f"{description}\n\n#Shorts"

    body = {
        "snippet": {
            "title": title[:100],  # YouTube title limit
            "description": description[:5000],
            "tags": tags,
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"Upload progress: {int(status.progress() * 100)}%")

    video_id = response["id"]

    if thumbnail_path:
        try:
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumbnail_path, mimetype="image/jpeg"),
            ).execute()
            print(f"Custom thumbnail set for {video_id}")
        except Exception as e:
            # A thumbnail failure should never take down an otherwise-
            # successful upload. Common cause: the channel isn't phone-
            # verified yet -- custom thumbnails require verification
            # (https://www.youtube.com/verify). The video itself is fine;
            # YouTube just falls back to an auto-picked frame.
            print(f"WARNING: could not set custom thumbnail ({e}). "
                  f"Video uploaded fine, just without a custom thumbnail. "
                  f"If your channel isn't phone-verified, that's the likely cause.")

    return video_id


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("video_path")
    parser.add_argument("title")
    parser.add_argument("description")
    parser.add_argument("token_path")
    parser.add_argument("--client_secret", default=None)
    parser.add_argument("--tags", nargs="*", default=[])
    parser.add_argument("--category_id", default="27")
    parser.add_argument("--short", action="store_true")
    args = parser.parse_args()

    video_id = upload_video(
        args.video_path, args.title, args.description, args.tags,
        args.category_id, args.token_path, args.client_secret,
        is_short=args.short,
    )
    print(f"Uploaded: https://youtube.com/watch?v={video_id}")
