"""Unit tests for Spotify OAuth helper."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from spotify_auth import exchange_code_for_tokens


class TestSpotifyAuth(unittest.TestCase):
    @patch("spotify_auth.requests.post")
    def test_exchange_code_success(self, mock_post: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "mock_access",
            "refresh_token": "mock_refresh",
            "expires_in": 3600,
        }
        mock_post.return_value = mock_resp

        tokens = exchange_code_for_tokens(
            "client_id", "client_secret", "code_123", "http://127.0.0.1:8888/callback"
        )
        self.assertEqual(tokens["refresh_token"], "mock_refresh")
        self.assertEqual(tokens["access_token"], "mock_access")

    @patch("spotify_auth.requests.post")
    def test_exchange_code_failure(self, mock_post: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.return_value = {
            "error": "invalid_grant",
            "error_description": "Invalid authorization code",
        }
        mock_post.return_value = mock_resp

        with self.assertRaises(RuntimeError) as ctx:
            exchange_code_for_tokens(
                "client_id", "client_secret", "bad_code", "http://127.0.0.1:8888/callback"
            )
        self.assertIn("Token exchange failed", str(ctx.exception))
        self.assertIn("Invalid authorization code", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
