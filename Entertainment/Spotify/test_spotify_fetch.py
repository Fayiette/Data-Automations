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

    @patch("spotify_fetch.spotipy.Spotify")
    @patch("spotify_fetch.get_spotify_token")
    def test_fetch_and_merge_counts_new_listens_and_songs(
        self, mock_get_token: MagicMock, mock_spotipy_cls: MagicMock
    ) -> None:
        import pandas as pd
        from spotify_fetch import fetch_and_merge

        mock_get_token.return_value = ("token_abc", None)
        mock_sp = MagicMock()
        mock_spotipy_cls.return_value = mock_sp

        # Mock 1 recently played track
        mock_sp.current_user_recently_played.return_value = {
            "items": [
                {
                    "played_at": "2026-11-22T19:00:00.000Z",
                    "track": {
                        "id": "track_1",
                        "name": "Track One",
                        "duration_ms": 180000,
                        "artists": [{"id": "artist_1", "name": "Artist One"}],
                        "album": {"name": "Album One", "release_date": "2026-01-01", "images": []},
                    },
                }
            ],
            "next": None,
        }
        mock_sp.artist.return_value = {"genres": ["pop"], "images": []}

        # Case 1: Brand new song and new listen
        existing_empty = {
            "listening_history": pd.DataFrame(columns=["played_at", "track_id"]),
            "songs": pd.DataFrame(columns=["track_id", "track_name"]),
            "albums": pd.DataFrame(columns=["track_id", "album_name"]),
            "artists": pd.DataFrame(columns=["artist_id", "artist_name"]),
        }
        with patch.dict(
            "os.environ",
            {
                "SPOTIFY_CLIENT_ID": "cid",
                "SPOTIFY_CLIENT_SECRET": "sec",
                "SPOTIFY_REFRESH_TOKEN": "ref",
            },
        ):
            _, added_listens, added_songs = fetch_and_merge(existing_empty)
            self.assertEqual(added_listens, 1)
            self.assertEqual(added_songs, 1)

        # Case 2: Same song already in songs catalog, but new play timestamp
        existing_with_song = {
            "listening_history": pd.DataFrame(
                [{"played_at": "2026-11-22T18:00:00.000Z", "track_id": "track_1"}]
            ),
            "songs": pd.DataFrame([{"track_id": "track_1", "track_name": "Track One"}]),
            "albums": pd.DataFrame([{"track_id": "track_1", "album_name": "Album One"}]),
            "artists": pd.DataFrame([{"artist_id": "artist_1", "artist_name": "Artist One"}]),
        }
        with patch.dict(
            "os.environ",
            {
                "SPOTIFY_CLIENT_ID": "cid",
                "SPOTIFY_CLIENT_SECRET": "sec",
                "SPOTIFY_REFRESH_TOKEN": "ref",
            },
        ):
            _, added_listens, added_songs = fetch_and_merge(existing_with_song)
            self.assertEqual(added_listens, 1)
            self.assertEqual(added_songs, 0)

    def test_redact_secrets_preserves_label_and_discord_mention(self) -> None:
        from spotify_r2 import configure_logging, discord_user_prefix, redact_secrets

        with patch.dict(
            "os.environ",
            {
                "SPOTIFY_CLIENT_SECRET": "sec_val_12345",
                "R2_ENDPOINT": "https://secret-r2.invalid/path?x=1",
                "SPOTIFY_DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/1/abc",
                "DISCORD_USER_ID": "998877665544332211",
            },
        ):
            msg = (
                f"{discord_user_prefix()}[FAILED] Spotify Fetch failed: "
                "sec_val_12345 https%3A%2F%2Fsecret-r2.invalid%2Fpath%3Fx%3D1"
            )
            redacted = redact_secrets(msg)
            self.assertNotIn("sec_val_12345", redacted)
            self.assertNotIn("secret-r2.invalid", redacted)
            self.assertIn("<@998877665544332211>", redacted)
            self.assertIn("Spotify Fetch", redacted)

        configure_logging()
        import logging

        self.assertEqual(logging.getLogger("spotipy").level, logging.WARNING)

    @patch("spotify_fetch.requests.post")
    def test_get_spotify_token_omits_raw_response_text(self, mock_post: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.side_effect = ValueError("not json")
        mock_resp.text = "SENSITIVE_UPSTREAM_BODY_XYZ"
        mock_post.return_value = mock_resp

        with self.assertRaises(RuntimeError) as ctx:
            get_spotify_token("cid", "csec", "ref")
        self.assertNotIn("SENSITIVE_UPSTREAM_BODY_XYZ", str(ctx.exception))

    def test_upload_file_if_changed_defaults_private_acl(self) -> None:
        from pathlib import Path
        import tempfile
        from spotify_r2 import upload_file_if_changed

        mock_client = MagicMock()
        mock_client.get_object.side_effect = Exception("missing")
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "sample.csv"
            target.write_text("a,b\n1,2\n", encoding="utf-8")
            result = upload_file_if_changed(mock_client, "bucket", "Spotify/sample.csv", target)

        self.assertEqual(result, "uploaded")
        _, kwargs = mock_client.upload_file.call_args
        self.assertNotIn("ACL", kwargs["ExtraArgs"])


if __name__ == "__main__":
    unittest.main()
