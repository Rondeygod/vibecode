from collections import deque
from pathlib import Path
import time

from utils.persistence import (
    initialize_db,
    load_currents,
    load_queues,
    load_settings,
    save_current,
    save_queue,
    save_setting,
)

# In-memory state per guild
queue_map = {}      # guild_id -> deque[song]
current_map = {}    # guild_id -> dict(song=..., started_at=epoch_seconds)
settings_map = {}   # guild_id -> dict
_persistence_enabled = False


def init_persistence(db_path: str | Path):
    """Initialize DB-backed state and hydrate in-memory maps."""
    global _persistence_enabled
    initialize_db(db_path)

    for guild_id, songs in load_queues().items():
        queue_map[guild_id] = deque(songs)
    current_map.update(load_currents())

    loaded_settings = load_settings()
    settings_map.update(loaded_settings)

    _persistence_enabled = True


def _persist_queue(guild_id):
    if _persistence_enabled:
        save_queue(guild_id, list(get_queue(guild_id)))


def _persist_current(guild_id):
    if _persistence_enabled:
        save_current(guild_id, get_current(guild_id))


def _persist_setting(guild_id, key, value):
    if _persistence_enabled:
        save_setting(guild_id, key, value)


def set_current(guild_id, song: dict):
    """Set currently playing song metadata for a guild."""
    current_map[guild_id] = {"song": song, "started_at": time.time()}
    _persist_current(guild_id)


def get_current(guild_id):
    return current_map.get(guild_id)


def clear_current(guild_id):
    current_map.pop(guild_id, None)
    _persist_current(guild_id)


def get_queue(guild_id):
    """Return the mutable per-guild queue (creates one if missing)."""
    return queue_map.setdefault(guild_id, deque())


def reset_queue(guild_id):
    queue_map[guild_id] = deque()
    _persist_queue(guild_id)


def add_to_queue(guild_id, songs):
    """Append one or more songs to the end of the queue."""
    get_queue(guild_id).extend(songs)
    _persist_queue(guild_id)


def prepend_to_queue(guild_id, song):
    get_queue(guild_id).appendleft(song)
    _persist_queue(guild_id)


def pop_next_song(guild_id):
    """Pop and return the next queued song, persisting queue changes."""
    q = get_queue(guild_id)
    song = q.popleft() if q else None
    _persist_queue(guild_id)
    return song


def peek_next_song(guild_id):
    q = get_queue(guild_id)
    return q[0] if q else None


def get_total_duration(guild_id):
    return sum(song.get("duration", 0) for song in get_queue(guild_id))


def get_setting(guild_id, key, default=None):
    return settings_map.get(guild_id, {}).get(key, default)


def set_setting(guild_id, key, value):
    settings_map.setdefault(guild_id, {})[key] = value
    _persist_setting(guild_id, key, value)


def get_known_guild_ids():
    guild_ids = set(queue_map.keys()) | set(current_map.keys()) | set(settings_map.keys())
    return sorted(guild_ids)
