"""Local OAuth helper tool for Spotify refresh token generation.

Runs authorization code flow locally to obtain a SPOTIFY_REFRESH_TOKEN
with the 'user-read-recently-played' scope.
"""

from __future__ import annotations

import base64
import os
import sys
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Optional

import requests
from spotify_r2 import load_repo_env

REDIRECT_URI = "http://127.0.0.1:8888/callback"
PORT = 8888
SCOPE = "user-read-recently-played"


class _OAuthCallbackHandler(BaseHTTPRequestHandler):
    auth_code: Optional[str] = None
    auth_error: Optional[str] = None

    def do_GET(self) -> None:  # noqa: N802
        parsed_url = urllib.parse.urlparse(self.path)
        if parsed_url.path == "/callback":
            query = urllib.parse.parse_qs(parsed_url.query)
            if "code" in query:
                _OAuthCallbackHandler.auth_code = query["code"][0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(
                    b"<html><body><h2>Authorization successful!</h2>"
                    b"<p>You can close this browser tab and return to the terminal.</p></body></html>"
                )
            elif "error" in query:
                _OAuthCallbackHandler.auth_error = query["error"][0]
                self.send_response(400)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(
                    b"<html><body><h2>Authorization failed!</h2>"
                    b"<p>Spotify rejected authorization.</p></body></html>"
                )
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        # Suppress default server access logs to keep stdout clean
        pass


def exchange_code_for_tokens(
    client_id: str, client_secret: str, code: str, redirect_uri: str
) -> dict:
    auth_str = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    headers = {
        "Authorization": f"Basic {auth_str}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }
    resp = requests.post(
        "https://accounts.spotify.com/api/token",
        headers=headers,
        data=data,
        timeout=15,
    )
    if resp.status_code != 200:
        try:
            err = resp.json()
            err_code = err.get("error", "unknown")
            err_desc = err.get("error_description", resp.text)
        except Exception:
            err_code = "unknown"
            err_desc = resp.text
        raise RuntimeError(f"Token exchange failed (HTTP {resp.status_code}): {err_code} - {err_desc}")
    return resp.json()


def main() -> None:
    load_repo_env()
    client_id = os.getenv("SPOTIFY_CLIENT_ID", "").strip()
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET", "").strip()

    if not client_id:
        client_id = input("Enter SPOTIFY_CLIENT_ID: ").strip()
    if not client_secret:
        client_secret = input("Enter SPOTIFY_CLIENT_SECRET: ").strip()

    if not client_id or not client_secret:
        print("[ERROR] Both client ID and client secret are required.")
        sys.exit(1)

    auth_params = {
        "response_type": "code",
        "client_id": client_id,
        "scope": SCOPE,
        "redirect_uri": REDIRECT_URI,
    }
    auth_url = f"https://accounts.spotify.com/authorize?{urllib.parse.urlencode(auth_params)}"

    print("=" * 60)
    print("Spotify OAuth Token Generator")
    print("=" * 60)
    print(f"Make sure '{REDIRECT_URI}' is registered in your Spotify Developer App redirect URIs.")
    print("Opening browser for authorization...")
    print(f"If the browser does not open automatically, visit this URL:\n{auth_url}\n")

    try:
        server = HTTPServer(("127.0.0.1", PORT), _OAuthCallbackHandler)
    except OSError as e:
        print(f"[WARN] Could not bind local server on port {PORT} ({e}).")
        print("Please visit the authorization URL above, authorize, and paste the redirect URL or code below.")
        auth_code_input = input("Enter code or full redirected URL: ").strip()
        if "code=" in auth_code_input:
            parsed = urllib.parse.urlparse(auth_code_input)
            auth_code = urllib.parse.parse_qs(parsed.query).get("code", [None])[0]
        else:
            auth_code = auth_code_input
    else:
        webbrowser.open(auth_url)
        print("Waiting for callback on port 8888...")
        server.handle_request()
        server.server_close()
        auth_code = _OAuthCallbackHandler.auth_code

    if not auth_code:
        err = _OAuthCallbackHandler.auth_error or "No authorization code captured"
        print(f"[ERROR] Authorization failed: {err}")
        sys.exit(1)

    print("\nExchanging code for tokens...")
    try:
        tokens = exchange_code_for_tokens(client_id, client_secret, auth_code, REDIRECT_URI)
    except Exception as e:
        print(f"[ERROR] {e}")
        sys.exit(1)

    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        print("[ERROR] No refresh token returned in Spotify response.")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("[SUCCESS] Spotify authorization completed.")
    print("=" * 60)
    print(f"\nSPOTIFY_REFRESH_TOKEN:\n{refresh_token}\n")
    print("To configure GitHub Actions:")
    print("1. Go to repository Settings > Environments > prod > Environment secrets.")
    print("2. Set SPOTIFY_REFRESH_TOKEN to the value above.")
    print("3. Ensure SPOTIFY_CLIENT_SECRET matches your current rotated secret.")
    print("4. Update your local .env if running scripts locally.")
    print("=" * 60)


if __name__ == "__main__":
    main()
