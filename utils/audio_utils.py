import os
import shutil
from pathlib import Path

from discord import FFmpegPCMAudio


FFMPEG_BEFORE_OPTS = "-reconnect 1 -reconnect_streamed 1 -reconnect_at_eof 1 -reconnect_delay_max 5"
FFMPEG_OPTS = "-vn"


def _resolve_ffmpeg_executable() -> str:
    # 1) Explicit override
    custom = os.getenv("FFMPEG_PATH")
    if custom and Path(custom).exists():
        return custom

    # 2) Normal PATH lookup
    in_path = shutil.which("ffmpeg")
    if in_path:
        return in_path

    # 3) Common Windows install locations
    candidates = [
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe",
        Path(os.getenv("LOCALAPPDATA", ""))
        / "Microsoft"
        / "WinGet"
        / "Packages"
        / "Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
        / "ffmpeg-8.0.1-full_build"
        / "bin"
        / "ffmpeg.exe",
    ]
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return str(path)

    raise FileNotFoundError("ffmpeg was not found. Add ffmpeg to PATH or set FFMPEG_PATH.")


def get_ffmpeg_audio_source(stream_url: str) -> FFmpegPCMAudio:
    """Create an FFmpeg source for a stream URL."""
    return FFmpegPCMAudio(
        stream_url,
        executable=_resolve_ffmpeg_executable(),
        before_options=FFMPEG_BEFORE_OPTS,
        options=FFMPEG_OPTS,
    )


def format_duration(seconds: int) -> str:
    """Convert seconds to an mm:ss string."""
    minutes = seconds // 60
    sec = seconds % 60
    return f"{minutes}:{sec:02d}"


def detect_platform(url: str | None) -> str:
    value = (url or "").lower()
    if "youtube.com" in value or "youtu.be" in value:
        return "youtube"
    if "spotify.com" in value:
        return "spotify"
    return "default"


def make_progress_bar(current: int, total: int, bar_length: int = 20, platform: str = "default") -> str:
    """Generate a themed emoji progress bar."""
    palettes = {
        "youtube": ("🟦", "⬛", "▶️"),
        "spotify": ("🟦", "⬛", "🎵"),
        "default": ("🟦", "⬛", "🎶"),
    }
    filled, empty, prefix = palettes.get(platform, palettes["default"])

    safe_total = max(1, int(total))
    safe_current = max(0, min(int(current), safe_total))
    progress = safe_current / safe_total
    filled_count = int(round(bar_length * progress))
    if safe_current > 0:
        filled_count = max(1, filled_count)
    filled_count = min(bar_length, filled_count)

    bar = (filled * filled_count) + (empty * (bar_length - filled_count))
    return f"{prefix} {bar}"
