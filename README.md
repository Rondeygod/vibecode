# Discord Music Bot

Discord music bot focused on reliable voice playback with slash commands, queue persistence, and retry logic for expiring media URLs.

## What This Bot Does

- Accepts YouTube URLs, playlist URLs, or search terms.
- Resolves tracks using `yt-dlp`.
- Streams audio through FFmpeg into Discord voice.
- Persists queue/current/settings data in SQLite.
- Provides playback controls, queue view, health checks, and server playback stats.

Important: this bot streams audio and does not store local MP3/track files for normal playback.

## Features

- Slash commands plus optional `#play` text alias.
- Playlist queueing with a fast first-track path.
- Automatic stream URL refresh when links become stale.
- Retry on failed tracks (configurable retry budget in code constants).
- Now-playing embeds with progress bar and next-track preview.
- Idle auto-disconnect and empty-channel auto-leave behavior.
- Startup self-checks for FFmpeg, yt-dlp, and DB writability.
- Per-server stats (play time, top listeners, top tracks, skips, failures).

## Requirements

- Python `3.11+` (project currently runs on newer versions too).
- FFmpeg installed and reachable in PATH, or set `FFMPEG_PATH`.
- Node.js recommended for yt-dlp JS runtime compatibility on YouTube.

## Project Structure

- `musicbot.py`: main Discord bot, commands, playback loop, embeds, runtime checks.
- `youtube_handler.py`: yt-dlp extraction and normalization of tracks.
- `utils/audio_utils.py`: FFmpeg source creation and display helpers (duration/progress bar).
- `utils/queue_manager.py`: in-memory queue/current/settings + persistence hooks.
- `utils/persistence.py`: SQLite load/save operations.
- `musicbot_state.db`: default SQLite state file.
- `docker-compose.yml`, `Dockerfile`: containerized runtime.

## Setup (Local)

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## Environment Variables

Create `vibecode/.env`:

```env
DISCORD_TOKEN=your_discord_bot_token
ADMIN_USER_ID=your_discord_user_id
REQUIRE_DOCKER=1
FFMPEG_PATH=optional_full_path_to_ffmpeg_exe
MUSICBOT_STATE_DB=optional_custom_db_path
```

Variable notes:

- `DISCORD_TOKEN`: required; bot token from Discord Developer Portal.
- `ADMIN_USER_ID`: optional; receives bot error/startup warning DMs.
- `REQUIRE_DOCKER`: if `1/true`, bot exits when not running in Docker.
- `FFMPEG_PATH`: optional override when FFmpeg is not in PATH.
- `MUSICBOT_STATE_DB`: optional custom SQLite path (default is `vibecode/musicbot_state.db`).

## Run (Local)

```bash
python musicbot.py
```

If `REQUIRE_DOCKER=1`, local non-Docker runs will fail by design. Set `REQUIRE_DOCKER=0` for local debugging.

## Run (Docker)

Build and start:

```bash
docker compose up -d --build
```

Stop:

```bash
docker compose down
```

Follow logs:

```bash
docker compose logs -f musicbot
```

## Commands

- `/play query:<url or text>`: add a track or playlist and start playback if idle.
- `/skip`: skip current track.
- `/stop`: stop playback, clear queue/current, disconnect.
- `/clear`: clear queue/current and cleanup now-playing state.
- `/queue page:<number>`: show queue page.
- `/nowplaying`: show current track status.
- `/controls`: show ephemeral button controls (skip/stop/queue).
- `/debug enabled:<true|false>`: toggle debug mode per server.
- `/health`: runtime status (voice, FFmpeg, yt-dlp, DB writable).
- `/stats`: listening and usage stats per server.

Legacy alias:

- `#play <query>`

## Playback Flow (High-Level)

1. User calls `/play`.
2. Bot resolves track info via yt-dlp (`youtube_handler.py`).
3. Normalized track is placed in queue with requester metadata.
4. Bot ensures it is connected to the same voice channel.
5. FFmpeg is created from stream URL and played via Discord voice client.
6. On track end, bot records stats and moves to the next track.
7. If nothing remains, bot clears current state and schedules idle disconnect.

## Reliability Behaviors

- Timeout-protected extraction with retries.
- Stale stream URL refresh before playback.
- Failed-track requeue (up to retry limit) when playable URL can be refreshed.
- Admin DM notifications for runtime/startup errors (if configured).

## Troubleshooting

- Bot says FFmpeg missing:
  - Install FFmpeg and ensure `ffmpeg` is on PATH, or set `FFMPEG_PATH`.
- `/play` finds nothing:
  - Check internet connectivity, yt-dlp support, and query/link validity.
- Cannot join voice:
  - Ensure bot has `View Channel`, `Connect`, `Speak`, and voice activity permissions.
- Docker run fails locally:
  - If testing outside Docker, set `REQUIRE_DOCKER=0`.
- Commands not visible:
  - Wait for slash command sync on startup and verify bot scopes/intents in Discord.

## Data and Persistence

- Queue/current/settings are stored per guild (server).
- State is backed by SQLite and restored on startup.
- On startup, persisted "current track" is intentionally cleared to avoid stale playback markers.

## Notes for Development

- Keep command and playback logic in `musicbot.py`.
- Keep extraction normalization in `youtube_handler.py`.
- Keep FFmpeg/platform display helpers in `utils/audio_utils.py`.
- Keep queue/persistence abstraction in `utils/queue_manager.py`.
