# utils/embed_builder.py

import discord
from utils.audio_utils import format_duration, make_progress_bar
from utils.queue_manager import queue_length, get_total_duration

async def send_now_playing(ctx, song: dict) -> discord.Message:
    """
    Stuurt een embed naar Discord met informatie over het huidige nummer.
    """
    duration = song.get("duration", 1)
    total = queue_length(ctx.guild.id)
    remaining = get_total_duration(ctx.guild.id)

    embed = discord.Embed(
        title="Now Playing",
        description=f"[{song['title']}]({song['webpage_url']})"
    )
    embed.add_field(
        name="Duur huidig nummer", value=format_duration(duration), inline=True
    )
    embed.add_field(
        name="Track info",
        value=f"Nummer 1/{total} | {format_duration(remaining)} resterend",
        inline=True
    )
    if song.get("thumbnail"):
        embed.set_thumbnail(url=song["thumbnail"])

    return await ctx.send(embed=embed)

async def update_progress_bar(message: discord.Message, song: dict, elapsed: int):
    """
    Past de embed aan om een voortgangsbalk weer te geven.
    """
    duration = song.get("duration", 1)
    bar = make_progress_bar(elapsed, duration)
    embed = message.embeds[0]
    embed.description = (
        f"[{song['title']}]({song['webpage_url']})\n"
        f"{bar} {format_duration(elapsed)} / {format_duration(duration)}"
    )
    await message.edit(embed=embed)