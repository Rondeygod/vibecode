import asyncio
import logging
import os
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from youtube_handler import get_audio_info, get_audio_info_fast
from utils.audio_utils import detect_platform, format_duration, get_ffmpeg_audio_source, make_progress_bar
from utils.queue_manager import (
    add_to_queue,
    clear_current,
    get_current,
    get_queue,
    get_known_guild_ids,
    get_setting,
    get_total_duration,
    init_persistence,
    peek_next_song,
    pop_next_song,
    prepend_to_queue,
    reset_queue,
    set_current,
    set_setting,
)


EXTRACT_TIMEOUT_SECONDS = 45
STREAM_REFRESH_AFTER_SECONDS = 20 * 60
MAX_STREAM_RETRIES = 2
PROGRESS_UPDATE_INTERVAL_SECONDS = 30
INACTIVITY_DISCONNECT_SECONDS = 15 * 60
QUEUE_PAGE_SIZE = 10
EXTRACT_ATTEMPTS = 2


load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing. Add it to vibecode/.env")
try:
    ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0") or 0)
except ValueError:
    ADMIN_USER_ID = 0
    logger = logging.getLogger("musicbot")
    logger.warning("Invalid ADMIN_USER_ID in .env; DM alerts disabled.")

STATE_DB = Path(
    os.getenv(
        "MUSICBOT_STATE_DB",
        str(Path(__file__).resolve().parent / "musicbot_state.db"),
    )
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s level=%(levelname)s event=%(message)s",
)
logger = logging.getLogger("musicbot")

REQUIRE_DOCKER = os.getenv("REQUIRE_DOCKER", "1").strip().lower() in {"1", "true", "yes", "on"}
if REQUIRE_DOCKER and not Path("/.dockerenv").exists():
    raise RuntimeError(
        "This bot is configured to run only in Docker. Use `docker compose up -d --build` from vibecode/."
    )

intents = discord.Intents.all()
bot = commands.Bot(command_prefix=["#"], intents=intents)

channel_map: dict[int, discord.abc.Messageable] = {}
progress_tasks: dict[int, asyncio.Task] = {}
idle_disconnect_tasks: dict[int, asyncio.Task] = {}
now_playing_messages: dict[int, discord.Message] = {}
_persistence_initialized = False
runtime_checks: dict[str, str] = {}


def _error_id() -> str:
    return uuid.uuid4().hex[:8]


def log_event(level: int, event: str, **fields):
    """Structured logger wrapper used throughout the bot."""
    if fields:
        payload = " ".join(f"{k}={fields[k]!r}" for k in sorted(fields))
        logger.log(level, f"{event} {payload}")
    else:
        logger.log(level, event)


def _dm_enabled() -> bool:
    return ADMIN_USER_ID > 0


async def notify_admin_error(title: str, details: str):
    """Send operational warnings/errors to ADMIN_USER_ID when configured."""
    if not _dm_enabled():
        return
    try:
        user = bot.get_user(ADMIN_USER_ID)
        if user is None:
            user = await bot.fetch_user(ADMIN_USER_ID)
        if user is None:
            log_event(logging.WARNING, "admin_dm_user_not_found", admin_user_id=ADMIN_USER_ID)
            return
        message = f"**{title}**\n{details}"
        if len(message) > 1900:
            message = message[:1900] + "..."
        await user.send(message)
    except Exception as exc:
        log_event(logging.WARNING, "admin_dm_failed", admin_user_id=ADMIN_USER_ID, error=repr(exc))


def get_bot_member(guild: discord.Guild | None) -> discord.Member | None:
    if guild is None or bot.user is None:
        return None
    return guild.me or guild.get_member(bot.user.id)


def debug_enabled(guild_id: int) -> bool:
    return bool(get_setting(guild_id, "debug_mode", False))


def increment_stat(guild_id: int, key: str, delta: int = 1):
    current = int(get_setting(guild_id, key, 0) or 0)
    set_setting(guild_id, key, max(0, current + delta))


def increment_bucket_stat(
    guild_id: int,
    key: str,
    bucket_key: str,
    delta: int = 1,
    max_buckets: int | None = None,
):
    stats = dict(get_setting(guild_id, key, {}) or {})
    current = int(stats.get(bucket_key, 0) or 0)
    stats[bucket_key] = max(0, current + delta)
    if max_buckets and len(stats) > max_buckets:
        for stale_key in sorted(stats.keys())[:-max_buckets]:
            stats.pop(stale_key, None)
    set_setting(guild_id, key, stats)


def add_play_seconds(guild_id: int, seconds: int):
    increment_stat(guild_id, "stats_total_play_seconds", max(0, int(seconds)))


def format_stats_duration(total_seconds: int) -> str:
    total_seconds = max(0, int(total_seconds))
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    return f"{hours}h {minutes}m"


def _stats_date_key(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def _stats_week_key(ts: float) -> str:
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    iso = dt.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _top_items(mapping: dict, limit: int = 5):
    pairs = [(str(k), int(v or 0)) for k, v in (mapping or {}).items() if int(v or 0) > 0]
    pairs.sort(key=lambda kv: kv[1], reverse=True)
    return pairs[:limit]


def _track_label(song: dict) -> str:
    title = (song.get("title") or "Unknown").strip()
    return title[:100]


def record_completed_play(guild_id: int, song: dict, played_seconds: int, finished_at: float):
    played_seconds = max(0, int(played_seconds))
    increment_stat(guild_id, "stats_completed_tracks")
    add_play_seconds(guild_id, played_seconds)

    requester_id = song.get("requester_id")
    if requester_id is not None:
        user_key = str(requester_id)
        increment_bucket_stat(guild_id, "stats_user_completed_tracks", user_key, 1)
        increment_bucket_stat(guild_id, "stats_user_play_seconds", user_key, played_seconds)

    day_key = _stats_date_key(finished_at)
    week_key = _stats_week_key(finished_at)
    increment_bucket_stat(guild_id, "stats_daily_completed_tracks", day_key, 1, max_buckets=120)
    increment_bucket_stat(guild_id, "stats_daily_play_seconds", day_key, played_seconds, max_buckets=120)
    increment_bucket_stat(guild_id, "stats_weekly_completed_tracks", week_key, 1, max_buckets=60)
    increment_bucket_stat(guild_id, "stats_weekly_play_seconds", week_key, played_seconds, max_buckets=60)

    track_key = _track_label(song)
    increment_bucket_stat(guild_id, "stats_track_plays", track_key, 1, max_buckets=300)


async def send_error(interaction: discord.Interaction, message: str, err: Exception):
    err_id = _error_id()
    guild_id = interaction.guild.id if interaction.guild else None
    command_name = interaction.command.name if interaction.command else "unknown"
    user_id = interaction.user.id if interaction.user else None
    log_event(
        logging.ERROR,
        "command_error",
        error_id=err_id,
        guild_id=guild_id,
        command=command_name,
        error=repr(err),
    )
    await notify_admin_error(
        "Music Bot Error",
        (
            f"error-id: `{err_id}`\n"
            f"guild: `{guild_id}`\n"
            f"user: `{user_id}`\n"
            f"command: `{command_name}`\n"
            f"message: {message}\n"
            f"error: `{repr(err)}`"
        ),
    )
    text = message
    try:
        if hasattr(interaction, "response") and not interaction.response.is_done():
            await interaction.response.send_message(text, ephemeral=True)
        else:
            await interaction.followup.send(text, ephemeral=True)
    except Exception as send_exc:
        log_event(logging.ERROR, "error_reply_failed", error=repr(send_exc), original_error=repr(err))


async def precheck_play_permissions(interaction: discord.Interaction) -> bool:
    """Validate voice presence and required channel permissions before playback."""
    if interaction.user.voice is None or interaction.user.voice.channel is None:
        await interaction.followup.send("You must be in a voice channel.", ephemeral=True)
        return False

    voice_channel = interaction.user.voice.channel
    me = get_bot_member(interaction.guild)
    if me is None:
        log_event(logging.WARNING, "bot_member_missing", guild_id=interaction.guild.id if interaction.guild else None)
        await interaction.followup.send(
            "I couldn't validate my permissions in this server. Please try again.",
            ephemeral=True,
        )
        return False

    perms = voice_channel.permissions_for(me)
    required = [
        ("view_channel", "View Channel"),
        ("connect", "Connect"),
        ("speak", "Speak"),
        ("use_voice_activation", "Use Voice Activity"),
    ]
    missing = [label for attr, label in required if not getattr(perms, attr, False)]
    if missing:
        log_event(
            logging.WARNING,
            "voice_permission_missing",
            guild_id=interaction.guild.id if interaction.guild else None,
            channel_id=voice_channel.id if voice_channel else None,
            missing=missing,
        )
        await interaction.followup.send(
            f"I can't join/play in **{voice_channel.name}**. Missing permissions: {', '.join(missing)}.",
            ephemeral=True,
        )
        return False

    return True


def run_startup_self_checks() -> dict[str, str]:
    """Collect runtime diagnostics surfaced by /health and startup logs."""
    checks: dict[str, str] = {}

    ffmpeg_path = shutil.which("ffmpeg")
    checks["ffmpeg"] = ffmpeg_path if ffmpeg_path else "missing"

    try:
        import yt_dlp  # type: ignore

        checks["yt_dlp"] = getattr(yt_dlp, "version", None).__version__ if hasattr(getattr(yt_dlp, "version", None), "__version__") else getattr(yt_dlp, "__version__", "unknown")
    except Exception as exc:
        checks["yt_dlp"] = f"error:{exc.__class__.__name__}"

    try:
        db_dir = STATE_DB.parent
        db_dir.mkdir(parents=True, exist_ok=True)
        checks["db_dir"] = str(db_dir)
        checks["db_writable"] = str(os.access(db_dir, os.W_OK))
    except Exception as exc:
        checks["db_dir"] = f"error:{exc.__class__.__name__}"
        checks["db_writable"] = "False"

    checks["python"] = os.sys.version.split()[0]
    return checks


async def safe_defer(interaction: discord.Interaction) -> bool:
    try:
        if not interaction.response.is_done():
            await interaction.response.defer(thinking=True)
        return True
    except discord.NotFound as exc:
        # Interaction token expired or unknown; nothing to reply to anymore.
        log_event(
            logging.WARNING,
            "interaction_expired_before_defer",
            guild_id=interaction.guild.id if interaction.guild else None,
            error=repr(exc),
        )
        return False
    except discord.HTTPException as exc:
        log_event(
            logging.ERROR,
            "interaction_defer_failed",
            guild_id=interaction.guild.id if interaction.guild else None,
            error=repr(exc),
        )
        return False


def prepare_track(track: dict, requester: str, requester_id: int | None = None) -> dict:
    """Attach requester/runtime metadata to a normalized track payload."""
    item = dict(track)
    item["requester"] = requester
    if requester_id is not None:
        item["requester_id"] = int(requester_id)
    item["retry_count"] = int(item.get("retry_count", 0))
    item["extracted_at"] = int(time.time())
    return item


def build_queue_embed(guild_id: int, page: int = 1, per_page: int = QUEUE_PAGE_SIZE) -> discord.Embed:
    """Render a paginated queue embed for a guild."""
    queue = list(get_queue(guild_id))
    total = len(queue)
    pages = max(1, (total + per_page - 1) // per_page)
    page = min(max(1, page), pages)
    start = (page - 1) * per_page
    end = min(start + per_page, total)

    embed = discord.Embed(title="Queue", color=discord.Color.blue())
    if total == 0:
        embed.description = "The queue is empty."
        return embed

    for i, song in enumerate(queue[start:end], start + 1):
        embed.add_field(
            name=f"{i}. {song.get('title', 'Unknown')}",
            value=f"Requested by: {song.get('requester', 'Unknown')}",
            inline=False,
        )
    embed.set_footer(text=f"Page {page}/{pages} | Total: {total} tracks")
    return embed


def build_now_playing_embed(guild_id: int, title: str = "Now playing") -> discord.Embed | None:
    """Render the active track card with progress and queue timing context."""
    cur = get_current(guild_id)
    if not cur:
        return None

    song = cur["song"]
    started_at = cur["started_at"]
    dur = int(song.get("duration", 0))
    elapsed = max(0, int(time.time() - started_at))
    remaining = max(0, dur - elapsed)
    source_url = song.get("webpage_url") or song.get("url")
    platform = detect_platform(source_url)
    progress = make_progress_bar(min(elapsed, max(1, dur)), max(1, dur), bar_length=14, platform=platform)

    nxt = peek_next_song(guild_id)
    total_q = get_total_duration(guild_id)
    total_remaining = remaining + total_q
    platform_colors = {
        "youtube": discord.Color.from_rgb(255, 0, 0),
        "spotify": discord.Color.from_rgb(30, 215, 96),
        "default": discord.Color.green(),
    }
    embed_color = platform_colors.get(platform, platform_colors["default"])

    embed = discord.Embed(
        title=title,
        description=song.get("title", "Unknown"),
        color=embed_color,
    )
    embed.add_field(
        name="Progress",
        value=f"{progress}\n{format_duration(elapsed)} / {format_duration(dur)}",
        inline=False,
    )
    embed.add_field(name="Time till next", value=format_duration(remaining), inline=True)
    embed.add_field(name="Remaining queue time", value=format_duration(total_remaining), inline=True)
    if nxt:
        embed.add_field(name="Next song", value=nxt.get("title", "Unknown"), inline=False)
    if song.get("thumbnail"):
        embed.set_thumbnail(url=song["thumbnail"])
    return embed


def build_track_added_embed(song: dict, requester: str, queue_tracks: int, total_duration: int) -> discord.Embed:
    embed = discord.Embed(title="Track Added", color=discord.Color.blurple())
    embed.add_field(name="Song", value=song["title"], inline=False)
    embed.add_field(name="Requester", value=requester, inline=True)
    embed.add_field(name="Duration", value=f"{song['duration'] // 60}:{song['duration'] % 60:02} min", inline=True)
    embed.add_field(name="Total Queue Tracks", value=str(queue_tracks), inline=True)
    embed.add_field(name="Total Queue Time", value=f"{total_duration // 60}:{total_duration % 60:02} min", inline=True)
    if song.get("thumbnail"):
        embed.set_thumbnail(url=song["thumbnail"])
    return embed


async def fetch_with_timeout(coro_factory, timeout_s: int):
    """
    Run an async fetch with timeout and a small retry budget.
    coro_factory must be a callable returning a fresh coroutine.
    """
    last_error = None
    for attempt in range(1, EXTRACT_ATTEMPTS + 1):
        try:
            return await asyncio.wait_for(coro_factory(), timeout=timeout_s)
        except asyncio.TimeoutError as exc:
            last_error = exc
            log_event(logging.WARNING, "extract_timeout", attempt=attempt, timeout=timeout_s)
        except Exception as exc:
            last_error = exc
            log_event(logging.WARNING, "extract_failed", attempt=attempt, error=repr(exc))
        if attempt < EXTRACT_ATTEMPTS:
            await asyncio.sleep(0.6)
    raise last_error or asyncio.TimeoutError("Audio fetch timed out")


async def refresh_song_if_stale(song: dict) -> dict:
    """Refresh expiring direct stream URLs from webpage_url when needed."""
    webpage_url = song.get("webpage_url")
    if not webpage_url:
        return song

    extracted_at = int(song.get("extracted_at", 0))
    stale = (time.time() - extracted_at) > STREAM_REFRESH_AFTER_SECONDS
    if not stale and song.get("url"):
        return song

    refreshed = await fetch_with_timeout(lambda: get_audio_info([webpage_url]), EXTRACT_TIMEOUT_SECONDS)
    if not refreshed:
        return song

    merged = prepare_track(
        refreshed[0],
        song.get("requester", "Unknown"),
        song.get("requester_id"),
    )
    merged["retry_count"] = int(song.get("retry_count", 0))
    return merged


async def ensure_voice(interaction: discord.Interaction):
    """Join or move to the requester's voice channel and return the client."""
    can_play = await precheck_play_permissions(interaction)
    if not can_play:
        return None

    voice_channel = interaction.user.voice.channel
    try:
        if interaction.guild.voice_client is None:
            await voice_channel.connect()
        elif interaction.guild.voice_client.channel != voice_channel:
            await interaction.guild.voice_client.move_to(voice_channel)
        return interaction.guild.voice_client
    except discord.Forbidden as exc:
        log_event(
            logging.WARNING,
            "voice_join_forbidden",
            guild_id=interaction.guild.id if interaction.guild else None,
            channel_id=voice_channel.id if voice_channel else None,
            error=repr(exc),
        )
        await interaction.followup.send(
            "I can't join that voice channel. Please check my Connect and Speak permissions.",
            ephemeral=True,
        )
        return None
    except (discord.ClientException, discord.HTTPException) as exc:
        log_event(
            logging.WARNING,
            "voice_join_failed",
            guild_id=interaction.guild.id if interaction.guild else None,
            channel_id=voice_channel.id if voice_channel else None,
            error=repr(exc),
        )
        await interaction.followup.send(
            "I couldn't join your voice channel. Please try again or check my voice permissions.",
            ephemeral=True,
        )
        return None


async def post_now_playing(guild: discord.Guild, text_channel):
    embed = build_now_playing_embed(guild.id, title="Now playing")
    if embed:
        await upsert_now_playing_message(guild.id, text_channel, embed)


async def upsert_now_playing_message(guild_id: int, text_channel, embed: discord.Embed):
    """Edit existing now-playing message or post a new one if missing."""
    existing = now_playing_messages.get(guild_id)
    if existing is not None:
        try:
            await existing.edit(embed=embed, view=PlayerControls())
            return
        except discord.NotFound:
            now_playing_messages.pop(guild_id, None)
        except Exception as exc:
            log_event(logging.WARNING, "now_playing_edit_failed", guild_id=guild_id, error=repr(exc))

    if text_channel is None:
        return
    try:
        message = await text_channel.send(embed=embed, view=PlayerControls())
        now_playing_messages[guild_id] = message
    except Exception as exc:
        log_event(logging.WARNING, "now_playing_send_failed", guild_id=guild_id, error=repr(exc))


async def bump_now_playing_to_bottom(guild_id: int, text_channel):
    """
    Repost the current now-playing embed so it becomes the newest message.
    This keeps the "active player card" at the bottom of chat.
    """
    embed = build_now_playing_embed(guild_id, title="Now playing")
    if embed is None or text_channel is None:
        return

    old_message = now_playing_messages.get(guild_id)
    try:
        new_message = await text_channel.send(embed=embed, view=PlayerControls())
        now_playing_messages[guild_id] = new_message
    except Exception as exc:
        log_event(logging.WARNING, "now_playing_bump_failed", guild_id=guild_id, error=repr(exc))
        return

    if old_message is not None and old_message.id != new_message.id:
        try:
            await old_message.delete()
        except discord.NotFound:
            pass
        except Exception as exc:
            log_event(logging.WARNING, "now_playing_old_delete_failed", guild_id=guild_id, error=repr(exc))


async def clear_now_playing_message(guild_id: int):
    message = now_playing_messages.pop(guild_id, None)
    if message is None:
        return
    try:
        await message.delete()
    except discord.NotFound:
        pass
    except Exception as exc:
        log_event(logging.WARNING, "now_playing_delete_failed", guild_id=guild_id, error=repr(exc))


async def progress_updater(guild_id: int):
    """Periodic task that refreshes the now-playing embed while a track is active."""
    while True:
        await asyncio.sleep(PROGRESS_UPDATE_INTERVAL_SECONDS)
        cur = get_current(guild_id)
        if not cur:
            return
        text_channel = channel_map.get(guild_id)
        if text_channel is None:
            continue
        embed = build_now_playing_embed(guild_id, title="Now playing")
        if embed is not None:
            try:
                await upsert_now_playing_message(guild_id, text_channel, embed)
            except Exception as exc:
                log_event(logging.WARNING, "progress_update_failed", guild_id=guild_id, error=repr(exc))


def ensure_progress_task(guild_id: int):
    task = progress_tasks.get(guild_id)
    if task and not task.done():
        return
    progress_tasks[guild_id] = asyncio.create_task(progress_updater(guild_id))


def stop_progress_task(guild_id: int):
    task = progress_tasks.pop(guild_id, None)
    if task and not task.done():
        task.cancel()


def cancel_idle_disconnect_task(guild_id: int):
    task = idle_disconnect_tasks.pop(guild_id, None)
    if task and not task.done():
        task.cancel()


def ensure_idle_disconnect_task(guild_id: int):
    """Schedule auto-disconnect when queue is empty and playback is idle."""
    existing = idle_disconnect_tasks.get(guild_id)
    if existing and not existing.done():
        return

    async def idle_disconnect_worker():
        try:
            await asyncio.sleep(INACTIVITY_DISCONNECT_SECONDS)
            guild = bot.get_guild(guild_id)
            if guild is None:
                return
            voice_client = guild.voice_client
            if not voice_client or not voice_client.is_connected():
                return
            if voice_client.is_playing():
                return
            if get_current(guild_id):
                return
            if len(get_queue(guild_id)) > 0:
                return

            text_channel = channel_map.get(guild_id)
            await voice_client.disconnect()
            await clear_now_playing_message(guild_id)
            cancel_idle_disconnect_task(guild_id)
            if text_channel is not None:
                await text_channel.send("I left the voice channel because I was inactive for 15 minutes.")
            log_event(logging.INFO, "left_inactive_voice_channel", guild_id=guild_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log_event(logging.WARNING, "idle_disconnect_failed", guild_id=guild_id, error=repr(exc))
        finally:
            idle_disconnect_tasks.pop(guild_id, None)

    idle_disconnect_tasks[guild_id] = asyncio.create_task(idle_disconnect_worker())


async def handle_failed_song(interaction: discord.Interaction, song: dict, reason: str):
    """Retry failed tracks when possible, otherwise skip forward in the queue."""
    increment_stat(interaction.guild.id, "stats_failed_tracks")
    retries = int(song.get("retry_count", 0))
    if retries < MAX_STREAM_RETRIES and song.get("webpage_url"):
        song["retry_count"] = retries + 1
        prepend_to_queue(interaction.guild.id, song)
        log_event(
            logging.WARNING,
            "song_retry_scheduled",
            guild_id=interaction.guild.id,
            retries=song["retry_count"],
            title=song.get("title", "unknown"),
            reason=reason,
        )
    else:
        log_event(
            logging.ERROR,
            "song_failed",
            guild_id=interaction.guild.id,
            title=song.get("title", "unknown"),
            reason=reason,
        )
    await play_next(interaction)


async def handle_queue_exhausted(guild_id: int):
    clear_current(guild_id)
    stop_progress_task(guild_id)
    await clear_now_playing_message(guild_id)
    ensure_idle_disconnect_task(guild_id)


async def maybe_start_playback(interaction: discord.Interaction):
    """Start playback only when connected and currently not playing."""
    voice_client = interaction.guild.voice_client
    if voice_client and voice_client.is_playing():
        return
    joined = await ensure_voice(interaction)
    if joined and joined.is_connected():
        await play_next(interaction)


async def play_next(interaction: discord.Interaction):
    """Core playback loop: pop queue, create source, play, then chain next track."""
    queue = get_queue(interaction.guild.id)
    if not queue:
        await handle_queue_exhausted(interaction.guild.id)
        return

    song = pop_next_song(interaction.guild.id)
    if not song:
        await handle_queue_exhausted(interaction.guild.id)
        return

    cancel_idle_disconnect_task(interaction.guild.id)
    try:
        song = await refresh_song_if_stale(song)
    except Exception as exc:
        await handle_failed_song(interaction, song, f"refresh_failed:{exc!r}")
        return

    set_current(interaction.guild.id, song)
    text_channel = channel_map.get(interaction.guild.id) or interaction.channel
    await post_now_playing(interaction.guild, text_channel)
    ensure_progress_task(interaction.guild.id)

    stream_url = song.get("url") or song.get("webpage_url")
    if not stream_url:
        await handle_failed_song(interaction, song, "missing_stream_url")
        return

    voice_client = interaction.guild.voice_client
    if not voice_client or not voice_client.is_connected():
        voice_client = await ensure_voice(interaction)
        if not voice_client or not voice_client.is_connected():
            return

    try:
        source = get_ffmpeg_audio_source(stream_url)
    except Exception as exc:
        await handle_failed_song(interaction, song, f"source_creation_failed:{exc!r}")
        return

    started_at = time.time()

    def after_playing(error):
        elapsed = time.time() - started_at
        failed_fast = error is not None or (
            int(song.get("duration", 0)) > 30 and elapsed < 3
        )

        if failed_fast:
            reason = repr(error) if error else "ffmpeg_ended_too_fast"
            fut = asyncio.run_coroutine_threadsafe(
                handle_failed_song(interaction, song, reason),
                bot.loop,
            )
        else:
            played_seconds = int(max(0, elapsed))
            finished_at = time.time()

            async def on_track_finished():
                record_completed_play(interaction.guild.id, song, played_seconds, finished_at)
                await play_next(interaction)

            fut = asyncio.run_coroutine_threadsafe(on_track_finished(), bot.loop)

        try:
            fut.result()
        except Exception as exc:
            log_event(logging.ERROR, "play_next_callback_failed", error=repr(exc))

    try:
        voice_client.play(source, after=after_playing)
    except Exception as exc:
        await handle_failed_song(interaction, song, f"voice_play_failed:{exc!r}")


class PlayerControls(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.primary)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            increment_stat(interaction.guild.id, "stats_skips")
            vc.stop()
            await interaction.response.send_message("Track skipped!", ephemeral=True)
        else:
            await interaction.response.send_message("Nothing is currently playing.", ephemeral=True)

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.danger)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc:
            vc.stop()
            await vc.disconnect()
            reset_queue(interaction.guild.id)
            clear_current(interaction.guild.id)
            stop_progress_task(interaction.guild.id)
            cancel_idle_disconnect_task(interaction.guild.id)
            await clear_now_playing_message(interaction.guild.id)
            await interaction.response.send_message("Bot stopped and disconnected.", ephemeral=True)
        else:
            await interaction.response.send_message("Bot is not connected.", ephemeral=True)

    @discord.ui.button(label="Queue", style=discord.ButtonStyle.secondary)
    async def queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            embed=build_queue_embed(interaction.guild.id, page=1),
            ephemeral=True,
        )


async def handle_play_request(interaction: discord.Interaction, query: str):
    """Resolve a user query, enqueue tracks, and trigger playback if idle."""
    channel_map[interaction.guild.id] = interaction.channel
    requester = interaction.user.display_name
    requester_id = interaction.user.id

    can_play = await precheck_play_permissions(interaction)
    if not can_play:
        return

    if debug_enabled(interaction.guild.id):
        log_event(logging.DEBUG, "play_requested", guild_id=interaction.guild.id, query=query)

    try:
        if "playlist" in query or ("list=" in query and "youtube.com" in query):
            first_tracks, rest_tracks = await fetch_with_timeout(
                lambda: get_audio_info_fast(query),
                EXTRACT_TIMEOUT_SECONDS,
            )
            if not first_tracks:
                await interaction.followup.send("No playable tracks were found in this playlist.")
                return

            prepared_first = [prepare_track(t, requester, requester_id) for t in first_tracks]
            add_to_queue(interaction.guild.id, prepared_first)

            queue = get_queue(interaction.guild.id)
            total_duration = sum(s.get("duration", 0) for s in queue)
            first = prepared_first[0]
            embed = build_track_added_embed(first, requester, len(queue), total_duration)
            await interaction.followup.send(embed=embed)
            await bump_now_playing_to_bottom(interaction.guild.id, interaction.channel)
            await maybe_start_playback(interaction)

            async def add_rest():
                prepared_rest = [prepare_track(t, requester, requester_id) for t in rest_tracks]
                add_to_queue(interaction.guild.id, prepared_rest)

            asyncio.create_task(add_rest())
            return

        yt_tracks = await fetch_with_timeout(
            lambda: get_audio_info([query]),
            EXTRACT_TIMEOUT_SECONDS,
        )
        prepared_tracks = [prepare_track(t, requester, requester_id) for t in yt_tracks]

        if prepared_tracks:
            add_to_queue(interaction.guild.id, prepared_tracks)
            queue = get_queue(interaction.guild.id)
            total_duration = sum(s.get("duration", 0) for s in queue)
            first = prepared_tracks[0]
            embed = build_track_added_embed(first, requester, len(queue), total_duration)
            await interaction.followup.send(embed=embed)
            await bump_now_playing_to_bottom(interaction.guild.id, interaction.channel)
            await maybe_start_playback(interaction)
        else:
            await interaction.followup.send("No tracks found.")
    except asyncio.TimeoutError as exc:
        log_event(
            logging.WARNING,
            "play_fetch_timeout",
            guild_id=interaction.guild.id if interaction.guild else None,
            user_id=interaction.user.id if interaction.user else None,
            query=query,
            error=repr(exc),
        )
        await send_error(interaction, "Timeout while fetching audio info.", exc)
    except Exception as exc:
        log_event(
            logging.ERROR,
            "play_fetch_failed",
            guild_id=interaction.guild.id if interaction.guild else None,
            user_id=interaction.user.id if interaction.user else None,
            query=query,
            error=repr(exc),
        )
        await send_error(interaction, "An error occurred while fetching audio info.", exc)


@bot.tree.command(name="play", description="Play a track, YouTube link, playlist, or search query.")
@app_commands.describe(query="YouTube link, playlist, or search query")
async def slash_play(interaction: discord.Interaction, query: str):
    ok = await safe_defer(interaction)
    if not ok:
        return
    await handle_play_request(interaction, query)


@bot.command(name="play")
async def play_cmd(ctx, *, query: str):
    class DummyResponse:
        async def defer(self, thinking=True):
            return

    class DummyFollowup:
        async def send(self, content=None, embed=None, view=None, ephemeral=False):
            return await ctx.send(content=content, embed=embed, view=view)

    class DummyInteraction:
        def __init__(self):
            self.guild = ctx.guild
            self.user = ctx.author
            self.channel = ctx.channel
            self.response = DummyResponse()
            self.followup = DummyFollowup()
            self.command = type("cmd", (), {"name": "play"})()

    dummy = DummyInteraction()
    await handle_play_request(dummy, query)


@bot.tree.command(name="skip", description="Skip the current track.")
async def slash_skip(interaction: discord.Interaction):
    voice_client = interaction.guild.voice_client
    if voice_client and voice_client.is_playing():
        increment_stat(interaction.guild.id, "stats_skips")
        voice_client.stop()
        await interaction.response.send_message("Track skipped!")
    else:
        await interaction.response.send_message("Nothing is currently playing.", ephemeral=True)


@bot.tree.command(name="stop", description="Stop playback and disconnect.")
async def slash_stop(interaction: discord.Interaction):
    voice_client = interaction.guild.voice_client
    if voice_client:
        voice_client.stop()
        await voice_client.disconnect()
        reset_queue(interaction.guild.id)
        clear_current(interaction.guild.id)
        stop_progress_task(interaction.guild.id)
        cancel_idle_disconnect_task(interaction.guild.id)
        await clear_now_playing_message(interaction.guild.id)
        await interaction.response.send_message("Bot stopped and disconnected.")
    else:
        await interaction.response.send_message("Bot is not connected to a voice channel.", ephemeral=True)


@bot.tree.command(name="clear", description="Clear the queue.")
async def slash_clear(interaction: discord.Interaction):
    reset_queue(interaction.guild.id)
    clear_current(interaction.guild.id)
    stop_progress_task(interaction.guild.id)
    await clear_now_playing_message(interaction.guild.id)
    ensure_idle_disconnect_task(interaction.guild.id)
    await interaction.response.send_message("Queue cleared.")


@bot.tree.command(name="queue", description="Show the queue.")
@app_commands.describe(page="Page number (default 1)")
async def slash_queue(interaction: discord.Interaction, page: int = 1):
    await interaction.response.send_message(embed=build_queue_embed(interaction.guild.id, page=page))


@bot.tree.command(name="controls", description="Show an ephemeral control panel.")
async def slash_controls(interaction: discord.Interaction):
    await interaction.response.send_message(
        "Player controls:",
        view=PlayerControls(),
        ephemeral=True,
    )


@bot.tree.command(name="nowplaying", description="Show the currently playing track.")
async def slash_nowplaying(interaction: discord.Interaction):
    embed = build_now_playing_embed(interaction.guild.id, title="Now Playing")
    if embed is None:
        await interaction.response.send_message("Nothing is currently playing.")
        return
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="debug", description="Enable or disable debug mode for this server.")
@app_commands.describe(enabled="True = on, False = off")
async def slash_debug(interaction: discord.Interaction, enabled: bool):
    set_setting(interaction.guild.id, "debug_mode", enabled)
    await interaction.response.send_message(f"Debug mode is now {'on' if enabled else 'off'}.")


@bot.tree.command(name="health", description="Show bot status and queue metrics.")
async def slash_health(interaction: discord.Interaction):
    queue_size = len(get_queue(interaction.guild.id))
    cur = get_current(interaction.guild.id)
    vc = interaction.guild.voice_client
    embed = discord.Embed(title="Health", color=discord.Color.orange())
    embed.add_field(name="Queue size", value=str(queue_size), inline=True)
    embed.add_field(name="In voice", value=str(bool(vc and vc.is_connected())), inline=True)
    embed.add_field(name="Playing", value=str(bool(vc and vc.is_playing())), inline=True)
    embed.add_field(name="Current song", value=cur["song"]["title"] if cur else "None", inline=False)
    embed.add_field(name="Debug mode", value=str(debug_enabled(interaction.guild.id)), inline=True)
    embed.add_field(name="FFmpeg", value=runtime_checks.get("ffmpeg", "unknown"), inline=False)
    embed.add_field(name="yt-dlp", value=runtime_checks.get("yt_dlp", "unknown"), inline=True)
    embed.add_field(name="DB writable", value=runtime_checks.get("db_writable", "unknown"), inline=True)
    embed.add_field(name="Python", value=runtime_checks.get("python", "unknown"), inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="stats", description="Show server playback statistics.")
async def slash_stats(interaction: discord.Interaction):
    now_ts = time.time()
    today_key = _stats_date_key(now_ts)
    week_key = _stats_week_key(now_ts)

    total_play_seconds = int(get_setting(interaction.guild.id, "stats_total_play_seconds", 0) or 0)
    completed_tracks = int(get_setting(interaction.guild.id, "stats_completed_tracks", 0) or 0)
    failed_tracks = int(get_setting(interaction.guild.id, "stats_failed_tracks", 0) or 0)
    skips = int(get_setting(interaction.guild.id, "stats_skips", 0) or 0)
    daily_seconds = dict(get_setting(interaction.guild.id, "stats_daily_play_seconds", {}) or {})
    daily_tracks = dict(get_setting(interaction.guild.id, "stats_daily_completed_tracks", {}) or {})
    weekly_seconds = dict(get_setting(interaction.guild.id, "stats_weekly_play_seconds", {}) or {})
    weekly_tracks = dict(get_setting(interaction.guild.id, "stats_weekly_completed_tracks", {}) or {})
    user_seconds = dict(get_setting(interaction.guild.id, "stats_user_play_seconds", {}) or {})
    track_plays = dict(get_setting(interaction.guild.id, "stats_track_plays", {}) or {})

    embed = discord.Embed(title="Server Stats", color=discord.Color.teal())
    embed.add_field(name="Total listening time", value=format_stats_duration(total_play_seconds), inline=False)
    embed.add_field(
        name="Today (UTC)",
        value=(
            f"{format_stats_duration(int(daily_seconds.get(today_key, 0) or 0))}"
            f" | {int(daily_tracks.get(today_key, 0) or 0)} tracks"
        ),
        inline=False,
    )
    embed.add_field(
        name="This week (UTC)",
        value=(
            f"{format_stats_duration(int(weekly_seconds.get(week_key, 0) or 0))}"
            f" | {int(weekly_tracks.get(week_key, 0) or 0)} tracks"
        ),
        inline=False,
    )
    embed.add_field(name="Completed tracks", value=str(completed_tracks), inline=True)
    embed.add_field(name="Skipped tracks", value=str(skips), inline=True)
    embed.add_field(name="Failed tracks", value=str(failed_tracks), inline=True)

    top_users = _top_items(user_seconds, limit=5)
    if top_users:
        lines = [f"<@{user_id}>: {format_stats_duration(seconds)}" for user_id, seconds in top_users]
        embed.add_field(name="Top listeners", value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="Top listeners", value="No data yet.", inline=False)

    top_tracks = _top_items(track_plays, limit=5)
    if top_tracks:
        lines = [f"{idx}. {title} ({plays} plays)" for idx, (title, plays) in enumerate(top_tracks, start=1)]
        embed.add_field(name="Top tracks", value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="Top tracks", value="No data yet.", inline=False)

    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.event
async def on_voice_state_update(member, before, after):
    """Disconnect and clear state when no human users remain in bot voice channel."""
    voice_client = member.guild.voice_client
    if not voice_client or not voice_client.channel:
        return

    # Ignore unrelated voice updates
    if before.channel != voice_client.channel and after.channel != voice_client.channel:
        return

    # Only disconnect if no human users remain in the bot's channel
    non_bot_members = [m for m in voice_client.channel.members if not m.bot]
    if len(non_bot_members) == 0:
        await voice_client.disconnect()
        reset_queue(member.guild.id)
        clear_current(member.guild.id)
        stop_progress_task(member.guild.id)
        cancel_idle_disconnect_task(member.guild.id)
        await clear_now_playing_message(member.guild.id)
        log_event(logging.INFO, "left_empty_voice_channel", guild_id=member.guild.id)


@bot.event
async def on_ready():
    """Initialize persistence/checks once, then sync slash commands."""
    global _persistence_initialized, runtime_checks
    if not _persistence_initialized:
        init_persistence(STATE_DB)
        # On process restart, persisted "current" can be stale.
        # Keep queue/settings, clear current playback markers.
        for guild_id in get_known_guild_ids():
            clear_current(guild_id)
        _persistence_initialized = True
        runtime_checks = run_startup_self_checks()
        log_event(
            logging.INFO,
            "startup_checks",
            ffmpeg=runtime_checks.get("ffmpeg"),
            yt_dlp=runtime_checks.get("yt_dlp"),
            db_dir=runtime_checks.get("db_dir"),
            db_writable=runtime_checks.get("db_writable"),
            python=runtime_checks.get("python"),
        )
        if runtime_checks.get("ffmpeg") == "missing":
            log_event(logging.WARNING, "ffmpeg_missing")
            await notify_admin_error("Startup Warning", "FFmpeg is missing from PATH.")
        if str(runtime_checks.get("db_writable")).lower() != "true":
            log_event(logging.WARNING, "db_not_writable", db_dir=runtime_checks.get("db_dir"))
            await notify_admin_error(
                "Startup Warning",
                f"Database directory is not writable.\ndb_dir: `{runtime_checks.get('db_dir')}`",
            )
        if str(runtime_checks.get("yt_dlp", "")).startswith("error:"):
            log_event(logging.WARNING, "yt_dlp_check_failed", detail=runtime_checks.get("yt_dlp"))
            await notify_admin_error(
                "Startup Warning",
                f"yt-dlp check failed: `{runtime_checks.get('yt_dlp')}`",
            )
    log_event(logging.INFO, "bot_ready", user=str(bot.user), db=str(STATE_DB))
    try:
        synced = await bot.tree.sync()
        log_event(logging.INFO, "slash_sync_ok", count=len(synced))
    except Exception as exc:
        log_event(logging.ERROR, "slash_sync_failed", error=repr(exc))
        await notify_admin_error("Startup Error", f"Slash command sync failed.\nerror: `{repr(exc)}`")


bot.run(TOKEN)
