import discord
from utils.audio_utils import format_duration, make_progress_bar
from utils.queue_manager import queue_length, get_total_duration


async def send_now_playing(ctx, song: dict) -> discord.Message:
    """
    Stuurt een embed met nummerinformatie, inclusief aanvrager en wachtrijtijd.
    """
    duration = song.get("duration", 1)
    total_tracks = queue_length(ctx.guild.id)
    total_remaining = get_total_duration(ctx.guild.id)
    requester = song.get("requester", "Onbekend")

    embed = discord.Embed(
        title="Now Playing",
        description=f"[{song['title']}]({song['webpage_url']})"
    )

    embed.add_field(name="Aangevraagd door", value=requester, inline=True)
    embed.add_field(name="Duur", value=format_duration(duration), inline=True)
    embed.add_field(
        name="Track info",
        value=f"Nummer 1 van {total_tracks} | {format_duration(total_remaining)} resterend",
        inline=True
    )

    if thumbnail := song.get("thumbnail"):
        embed.set_thumbnail(url=thumbnail)

    return await ctx.send(embed=embed)


async def update_progress_bar(message: discord.Message, song: dict, elapsed: int):
    """
    Werkt de originele 'Now Playing' embed bij met een voortgangsbalk en verstreken tijd.
    """
    duration = song.get("duration", 1)
    progress_bar = make_progress_bar(elapsed, duration)

    # Haal de eerste embed op en werk de beschrijving bij
    if not message.embeds:
        return  # Veiligheidscheck

    embed = message.embeds[0]
    embed.description = (
        f"[{song['title']}]({song['webpage_url']})\n"
        f"{progress_bar} {format_duration(elapsed)} / {format_duration(duration)}"
    )

    await message.edit(embed=embed)