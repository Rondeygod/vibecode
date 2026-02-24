import asyncio
import shutil
from pathlib import Path

import yt_dlp


def _resolve_node_executable() -> str | None:
    """Find a usable Node.js binary for yt-dlp JS runtime support."""
    in_path = shutil.which("node")
    if in_path:
        return in_path

    candidates = [
        r"C:\Program Files\nodejs\node.exe",
        r"C:\Program Files (x86)\nodejs\node.exe",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    return None


NODE_PATH = _resolve_node_executable()
JS_RUNTIMES = {"node": {"path": NODE_PATH}} if NODE_PATH else {"deno": {}}

YDL_BASE_OPTS = {
    "format": "bestaudio/best",
    "quiet": True,
    "noplaylist": True,
    "extract_flat": False,
    "skip_download": True,
    "source_address": "0.0.0.0",
    "js_runtimes": JS_RUNTIMES,
    "remote_components": ["ejs:github"],
}

YDL_PLAYLIST_FLAT_OPTS = {
    "quiet": True,
    "ignoreerrors": True,
    "extract_flat": "in_playlist",
    "skip_download": True,
    "noplaylist": False,
    "source_address": "0.0.0.0",
    "js_runtimes": JS_RUNTIMES,
    "remote_components": ["ejs:github"],
}


def _flatten(entries):
    """Flatten nested playlist entries into a single list."""
    out = []
    for item in entries or []:
        if not item:
            continue
        if isinstance(item, dict) and item.get("_type") == "playlist" and item.get("entries"):
            out.extend(_flatten(item["entries"]))
        else:
            out.append(item)
    return out


def _is_playlist(url: str) -> bool:
    return ("list=" in url) and ("youtube.com" in url or "youtu.be" in url)


async def _extract_info(query: str, opts: dict):
    """Run blocking yt-dlp extraction in a thread executor."""
    loop = asyncio.get_running_loop()
    with yt_dlp.YoutubeDL(opts) as ydl:
        return await loop.run_in_executor(None, lambda: ydl.extract_info(query, download=False))


def _normalize_track(info: dict, fallback_url: str) -> dict:
    """Map yt-dlp info to the bot's normalized track schema."""
    return {
        "title": info.get("title") or "Unknown",
        "url": info.get("url") or info.get("webpage_url") or fallback_url,
        "webpage_url": info.get("webpage_url") or fallback_url,
        "duration": int(info.get("duration") or 0),
        "thumbnail": info.get("thumbnail"),
    }


async def get_audio_info(queries: list[str]) -> list[dict]:
    """
    Resolve a list of URLs/search terms into normalized track dictionaries.
    """
    results: list[dict] = []

    for query in queries:
        opts = dict(YDL_BASE_OPTS)
        if not (query.startswith("http://") or query.startswith("https://")):
            opts["default_search"] = "ytsearch1"

        try:
            info = await _extract_info(query, opts)
        except yt_dlp.utils.DownloadError:
            continue

        if not info:
            continue

        if "entries" in info and info["entries"]:
            info = info["entries"][0]
        if not info:
            continue

        results.append(_normalize_track(info, query))

    return results


async def get_audio_info_fast(playlist_url: str, max_results: int = 500):
    """
    Playlist fast path: return (first_tracks, rest_tracks).
    """
    if not _is_playlist(playlist_url):
        single = await get_audio_info([playlist_url])
        return single[:1], single[1:]

    try:
        info = await _extract_info(playlist_url, dict(YDL_PLAYLIST_FLAT_OPTS))
    except yt_dlp.utils.DownloadError:
        info = None

    if not info or "entries" not in info:
        single = await get_audio_info([playlist_url])
        return single[:1], []

    entries = _flatten(info["entries"])
    urls = []
    for entry in entries:
        if not entry:
            continue
        if entry.get("webpage_url"):
            urls.append(entry["webpage_url"])
        elif entry.get("id"):
            urls.append(f"https://www.youtube.com/watch?v={entry['id']}")
        if len(urls) >= max_results:
            break

    if not urls:
        return [], []

    first = await get_audio_info([urls[0]])
    rest = await get_audio_info(urls[1:]) if len(urls) > 1 else []
    return first[:1], rest
