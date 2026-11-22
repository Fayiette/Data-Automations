# Spotify listening history

Fetches recently played tracks from the Spotify API, upserts dimension parquets and appends listening history, then syncs to **Cloudflare R2**.

## Setup

```bash
cd Spotify
pip install -r requirements.txt
cp .env.example .env
```

`[spotify_r2.py](spotify_r2.py)` loads only this folder's `.env` on import.


| Item                                                                  | Required             |
| --------------------------------------------------------------------- | -------------------- |
| R2 credentials                                                        | Yes                  |
| `R2_PREFIX`, four `R2_*_PARQUET_KEY` basenames                        | Yes                  |
| `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `SPOTIFY_REFRESH_TOKEN` | Yes                  |
| `SPOTIFY_MAX_PAGES`                                                   | Optional (default 2) |
| `DISCORD_*`                                                           | Optional             |


Object keys: `{R2_PREFIX}/{basename}` (e.g. `Spotify/history.parquet`). Each parquet also gets a CSV twin at `{R2_PREFIX}/{stem}.csv` (e.g. `history.csv`) — derived in code, no extra env vars.

## Strict R2 bootstrap

Each run **downloads all four parquets first**. Any missing object or download error **exits before** calling Spotify or uploading — prevents silent data loss from empty merges.

Seed R2 once with your four parquets (or empty schemas) under the prefix before the first CI run. CSV files are created on the first successful run (or upload manually from existing parquets if you want both formats immediately).

## Data files (parquet + CSV)


| Parquet basename  | CSV twin      | Role                                      |
| ----------------- | ------------- | ----------------------------------------- |
| `history.parquet` | `history.csv` | `played_at`, `track_id` (append + dedupe) |
| `songs.parquet`   | `songs.csv`   | Track dimension (upsert by `track_id`)    |
| `albums.parquet`  | `albums.csv`  | Album per track                           |
| `artists.parquet` | `artists.csv` | Artists (upsert by `artist_id`)           |


## Local

```bash
python spotify_fetch.py
```

## Spotify Authentication & Token Refresh

When running `spotify_fetch.py`, Spotify requires a valid `SPOTIFY_REFRESH_TOKEN` with the `user-read-recently-played` scope.

### Generating or Renewing a Refresh Token

If you encounter a token refresh failure (such as `invalid_grant` or after rotating your client secret):

1. **Configure Redirect URI**:
   In your [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) app settings, ensure:
   `http://127.0.0.1:8888/callback`
   is added to your **Redirect URIs** list.

2. **Run the local auth tool**:
   ```bash
   python spotify_auth.py
   ```
   This script prompts for your Client ID and Client Secret (or reads them from `.env`), opens your browser to authorize access, and outputs your fresh `SPOTIFY_REFRESH_TOKEN`.

3. **Update Secrets**:
   Update both `SPOTIFY_CLIENT_SECRET` and `SPOTIFY_REFRESH_TOKEN` under your GitHub repository's **Settings > Environments > prod > Environment secrets** (and in your local `.env`).

## GitHub Actions

`[.github/workflows/spotify-fetch.yml](.github/workflows/spotify-fetch.yml)` — alternating ~1.5h / ~1.7h crons, `environment: prod`, `concurrency: spotify-fetch`.

R2 layout and object basenames come from `**prod` secrets** (Spotify-prefixed to avoid monorepo clashes). The workflow maps them into the env vars the script reads:


| Secret (`prod`)                  | Maps to                  | Example value     |
| -------------------------------- | ------------------------ | ----------------- |
| `SPOTIFY_R2_PREFIX`              | `R2_PREFIX`              | `Spotify`         |
| `SPOTIFY_R2_HISTORY_PARQUET_KEY` | `R2_HISTORY_PARQUET_KEY` | `history.parquet` |
| `SPOTIFY_R2_SONGS_PARQUET_KEY`   | `R2_SONGS_PARQUET_KEY`   | `songs.parquet`   |
| `SPOTIFY_R2_ALBUMS_PARQUET_KEY`  | `R2_ALBUMS_PARQUET_KEY`  | `albums.parquet`  |
| `SPOTIFY_R2_ARTISTS_PARQUET_KEY` | `R2_ARTISTS_PARQUET_KEY` | `artists.parquet` |


Also required on `prod`: `R2_`* credentials, `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `SPOTIFY_REFRESH_TOKEN`, optional `DISCORD_*`.

Discord: success messages without `@` ping; upload line includes `listens +M | new songs +N` when data changed.
