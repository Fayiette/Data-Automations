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

    def test_oauth_callback_validates_state(self) -> None:
        import io
        from spotify_auth import _OAuthCallbackHandler

        _OAuthCallbackHandler.expected_state = "expected_nonce_123"
        _OAuthCallbackHandler.auth_code = None
        _OAuthCallbackHandler.auth_error = None

        handler = _OAuthCallbackHandler.__new__(_OAuthCallbackHandler)
        handler.path = "/callback?code=abc&state=wrong_nonce"
        handler.wfile = io.BytesIO()
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()

        handler.do_GET()
        handler.send_response.assert_called_with(400)
        self.assertIsNone(_OAuthCallbackHandler.auth_code)
        self.assertEqual(_OAuthCallbackHandler.auth_error, "OAuth state mismatch")

        handler.path = "/callback?code=abc&state=expected_nonce_123"
        handler.wfile = io.BytesIO()
        handler.send_response.reset_mock()
        handler.do_GET()
        handler.send_response.assert_called_with(200)
        self.assertEqual(_OAuthCallbackHandler.auth_code, "abc")


if __name__ == "__main__":
    unittest.main()
