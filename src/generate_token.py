"""
generate_token.py
One-time, local-only script to generate a channel's YouTube OAuth token.

This exists so you don't have to run a real upload just to authenticate --
it does nothing but open the browser login flow and save the resulting
token, using the same get_authenticated_service() function main.py uses
every day. Run this once per channel, locally (never in GitHub Actions --
the browser login can't work there).

Usage:
    python src/generate_token.py --client_secret client_secret.json --token tokens/jungle_ke_dost_token.pickle
"""
import argparse
from pathlib import Path

from src.upload_youtube import get_authenticated_service

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--client_secret", required=True,
                         help="Path to the client_secret.json downloaded from Google Cloud Console")
    parser.add_argument("--token", required=True,
                         help="Where to save the resulting token, e.g. tokens/jungle_ke_dost_token.pickle")
    args = parser.parse_args()

    Path(args.token).parent.mkdir(parents=True, exist_ok=True)
    get_authenticated_service(args.token, args.client_secret)
    print(f"\nToken saved to {args.token}")
    print("This will open a browser window the first time — log in with "
          "the Google account that owns the target YouTube channel, and "
          "approve the permission request.")
