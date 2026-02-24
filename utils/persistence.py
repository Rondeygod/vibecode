import json
import logging
import sqlite3
import threading
from tempfile import gettempdir
from pathlib import Path

_DB_PATH: Path | None = None
_LOCK = threading.Lock()
logger = logging.getLogger(__name__)


def _validate_db_path(path: Path) -> Path:
    """
    Ensure the parent directory exists and the sqlite file can be opened.
    Falls back to temp dir if the configured path is not writable.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
        conn.close()
        return path
    except Exception as exc:
        fallback = Path(gettempdir()) / "musicbot_state.db"
        fallback.parent.mkdir(parents=True, exist_ok=True)
        logger.warning(
            "Configured db path '%s' is not writable (%r). Falling back to '%s'.",
            path,
            exc,
            fallback,
        )
        conn = sqlite3.connect(fallback)
        conn.close()
        return fallback


def initialize_db(db_path: str | Path) -> None:
    global _DB_PATH
    _DB_PATH = _validate_db_path(Path(db_path))

    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS guild_queue (
                guild_id INTEGER NOT NULL,
                position INTEGER NOT NULL,
                song_json TEXT NOT NULL,
                PRIMARY KEY (guild_id, position)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS guild_current (
                guild_id INTEGER PRIMARY KEY,
                current_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS guild_settings (
                guild_id INTEGER NOT NULL,
                key TEXT NOT NULL,
                value_json TEXT NOT NULL,
                PRIMARY KEY (guild_id, key)
            )
            """
        )
        conn.commit()


def _connect() -> sqlite3.Connection:
    if _DB_PATH is None:
        raise RuntimeError("Database not initialized")
    return sqlite3.connect(_DB_PATH)


def save_queue(guild_id: int, songs: list[dict]) -> None:
    payloads = [(guild_id, i, json.dumps(song)) for i, song in enumerate(songs)]
    with _LOCK, _connect() as conn:
        conn.execute("DELETE FROM guild_queue WHERE guild_id = ?", (guild_id,))
        if payloads:
            conn.executemany(
                "INSERT INTO guild_queue (guild_id, position, song_json) VALUES (?, ?, ?)",
                payloads,
            )
        conn.commit()


def load_queues() -> dict[int, list[dict]]:
    by_guild: dict[int, list[dict]] = {}
    with _LOCK, _connect() as conn:
        rows = conn.execute(
            "SELECT guild_id, song_json FROM guild_queue ORDER BY guild_id, position"
        ).fetchall()
    for guild_id, song_json in rows:
        by_guild.setdefault(guild_id, []).append(json.loads(song_json))
    return by_guild


def save_current(guild_id: int, current: dict | None) -> None:
    with _LOCK, _connect() as conn:
        conn.execute("DELETE FROM guild_current WHERE guild_id = ?", (guild_id,))
        if current is not None:
            conn.execute(
                "INSERT INTO guild_current (guild_id, current_json) VALUES (?, ?)",
                (guild_id, json.dumps(current)),
            )
        conn.commit()


def load_currents() -> dict[int, dict]:
    out: dict[int, dict] = {}
    with _LOCK, _connect() as conn:
        rows = conn.execute("SELECT guild_id, current_json FROM guild_current").fetchall()
    for guild_id, current_json in rows:
        out[guild_id] = json.loads(current_json)
    return out


def save_setting(guild_id: int, key: str, value) -> None:
    with _LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO guild_settings (guild_id, key, value_json)
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id, key) DO UPDATE SET value_json=excluded.value_json
            """,
            (guild_id, key, json.dumps(value)),
        )
        conn.commit()


def load_settings() -> dict[int, dict]:
    out: dict[int, dict] = {}
    with _LOCK, _connect() as conn:
        rows = conn.execute("SELECT guild_id, key, value_json FROM guild_settings").fetchall()
    for guild_id, key, value_json in rows:
        out.setdefault(guild_id, {})[key] = json.loads(value_json)
    return out
