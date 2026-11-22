"""Unit tests for Spotify token refresh logic."""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

# Provide dummy env vars for R2 keys during test runs
for key in (
    "R2_HISTORY_PARQUET_KEY",
    "R2_SONGS_PARQUET_KEY",
    "R2_ALBUMS_PARQUET_KEY",
    "R2_ARTISTS_PARQUET_KEY",
):
    os.environ.setdefault(key, f"{key.lower()}.parquet")

import requests

from spotify_fetch import get_spotify_token


class TestSpotifyTokenRefresh(unittest.TestCase):
    @patch("spotify_fetch.requests.post")
    def test_get_spotify_token_success(self, mock_post: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "mock_access_123",
            "refresh_token": "mock_refresh_same",
        }
        mock_post.return_value = mock_resp

        access, refresh = get_spotify_token("client_id", "client_secret", "mock_refresh_same")
        self.assertEqual(access, "mock_access_123")
        self.assertEqual(refresh, "mock_refresh_same")
        self.assertEqual(mock_post.call_count, 1)

    @patch("spotify_fetch.requests.post")
    def test_get_spotify_token_rotation(self, mock_post: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "mock_access_456",
            "refresh_token": "mock_refresh_rotated",
        }
        mock_post.return_value = mock_resp

        access, refresh = get_spotify_token("client_id", "client_secret", "mock_refresh_old")
        self.assertEqual(access, "mock_access_456")
        self.assertEqual(refresh, "mock_refresh_rotated")

    @patch("spotify_fetch.requests.post")
    def test_get_spotify_token_invalid_grant_fails_fast(self, mock_post: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.return_value = {
            "error": "invalid_grant",
            "error_description": "Invalid refresh token",
        }
        mock_post.return_value = mock_resp

        with self.assertRaises(RuntimeError) as ctx:
            get_spotify_token("client_id", "client_secret", "bad_refresh")

        self.assertIn("invalid or expired", str(ctx.exception))
        self.assertIn("Regenerate SPOTIFY_REFRESH_TOKEN", str(ctx.exception))
        # Must fail immediately without retrying
        self.assertEqual(mock_post.call_count, 1)

    @patch("spotify_fetch.requests.post")
    def test_get_spotify_token_invalid_client_fails_fast(self, mock_post: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.json.return_value = {
            "error": "invalid_client",
            "error_description": "Invalid client secret",
        }
        mock_post.return_value = mock_resp

        with self.assertRaises(RuntimeError) as ctx:
            get_spotify_token("client_id", "bad_secret", "valid_refresh")

        self.assertIn("client authentication failed", str(ctx.exception))
        self.assertIn("Check SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET", str(ctx.exception))
        # Must fail immediately without retrying
        self.assertEqual(mock_post.call_count, 1)

    @patch("spotify_fetch.time.sleep")
    @patch("spotify_fetch.requests.post")
    def test_get_spotify_token_retries_on_transient_error(
        self, mock_post: MagicMock, mock_sleep: MagicMock
    ) -> None:
        # First attempt fails with network error, second succeeds
        mock_success = MagicMock()
        mock_success.status_code = 200
        mock_success.json.return_value = {
            "access_token": "mock_access_retry",
            "refresh_token": "token_123",
        }
        mock_post.side_effect = [
            requests.RequestException("Connection reset"),
            mock_success,
        ]

        access, refresh = get_spotify_token("client_id", "client_secret", "token_123")
        self.assertEqual(access, "mock_access_retry")
        self.assertEqual(mock_post.call_count, 2)
        self.assertEqual(mock_sleep.call_count, 1)

    @patch("spotify_fetch.time.sleep")
    @patch("spotify_fetch.requests.post")
    def test_get_spotify_token_exhausts_retries(
        self, mock_post: MagicMock, mock_sleep: MagicMock
    ) -> None:
        mock_post.side_effect = requests.RequestException("Network timeout")

        with self.assertRaises(RuntimeError) as ctx:
            get_spotify_token("client_id", "client_secret", "token_123")

        self.assertIn("failed after retries due to network or server issues", str(ctx.exception))
        self.assertEqual(mock_post.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)


if __name__ == "__main__":
    unittest.main()
