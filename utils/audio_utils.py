import discord
from discord import FFmpegPCMAudio

FFMPEG_BEFORE_OPTS = '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5'
FFMPEG_OPTS = '-vn'


def get_ffmpeg_audio_source(stream_url: str) -> FFmpegPCMAudio:
    """
    Maakt een FFmpegPCMAudio object aan voor een stream-URL.
    Dit wordt gebruikt om audio te streamen naar een Discord voice channel.
    """
    return FFmpegPCMAudio(
        stream_url,
        before_options=FFMPEG_BEFORE_OPTS,
        options=FFMPEG_OPTS
    )


def play_stream(voice_client, stream_url: str, after=None):
    """
    Speelt een audiostream af in het opgegeven voice channel.
    """
    source = get_ffmpeg_audio_source(stream_url)
    voice_client.play(source, after=after)


def format_duration(seconds: int) -> str:
    """
    Zet een aantal seconden om naar een mm:ss string.
    """
    minutes = seconds // 60
    sec = seconds % 60
    return f"{minutes}:{sec:02d}"


def make_progress_bar(current: int, total: int, bar_length: int = 20) -> str:
    """
    Genereert een visuele voortgangsbalk van blokjes (bijv. voor in een embed).
    """
    if total <= 0:
        return '░' * bar_length
    progress = int(bar_length * current / total)
    return '█' * progress + '░' * (bar_length - progress)