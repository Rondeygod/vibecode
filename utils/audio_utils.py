# utils/audio_utils.py

import discord

def format_duration(seconds: int) -> str:
    """Formatteer seconden naar mm:ss formaat."""
    minutes = seconds // 60
    sec = seconds % 60
    return f"{minutes}:{sec:02d}"

def make_progress_bar(current: int, total: int, bar_length: int = 20) -> str:
    """Genereer een tekstuele voortgangsbalk."""
    if total == 0:
        return '░' * bar_length
    progress = int(bar_length * current / total)
    bar = '█' * progress + '░' * (bar_length - progress)
    return bar

def get_ffmpeg_audio_source(stream_url: str) -> discord.FFmpegPCMAudio:
    """Retourneer een FFmpeg audio source object voor een stream URL."""
    return discord.FFmpegPCMAudio(
        stream_url,
        before_options='-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
        options='-vn'
    )