import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import logging
import os
from dotenv import load_dotenv

from spotify_handler import get_spotify_tracks, is_spotify_url
from youtube_handler import get_audio_info
from playlist_handler import flatten_playlist, filter_valid_tracks
from utils.queue_manager import (
    get_queue, reset_queue, add_to_queue, pop_next_song,
    peek_next_song, is_looping, toggle_looping, has_next
)
from utils.embed_builder import send_now_playing, update_progress_bar
from utils.audio_utils import format_duration, get_ffmpeg_audio_source

import yt_dlp

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
COOKIES_PATH = "cookies.txt"

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='#', intents=intents)


class ControlButtons(discord.ui.View):
    def __init__(self, ctx):
        super().__init__(timeout=None)
        self.ctx = ctx

    @discord.ui.button(label="⏭️ Skip", style=discord.ButtonStyle.primary)
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.ctx.voice_client and self.ctx.voice_client.is_playing():
            self.ctx.voice_client.stop()
            await interaction.response.send_message("Nummer geskipt.", ephemeral=True)

    @discord.ui.button(label="⏹️ Stop", style=discord.ButtonStyle.danger)
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.ctx.voice_client:
            await self.ctx.voice_client.disconnect()
            await interaction.response.send_message("Muziek gestopt en kanaal verlaten.", ephemeral=True)

    @discord.ui.button(label="📄 Queue", style=discord.ButtonStyle.secondary)
    async def queue_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        q = get_queue(interaction.guild.id)
        if not q:
            await interaction.response.send_message("De wachtrij is leeg.", ephemeral=True)
            return

        embed = discord.Embed(title="Wachtrij", description="Aankomende nummers:")
        total = 0
        for i, song in enumerate(list(q)[:10], start=1):
            title = song['title']
            url = song['webpage_url']
            duration = format_duration(song.get('duration', 0))
            requester = song.get('requester', "Onbekend")
            total += song.get('duration', 0)

            embed.add_field(
                name=f"{i}. {title}",
                value=f"[Link]({url}) | Duur: {duration} | Door: {requester}",
                inline=False
            )

        embed.set_footer(text=f"Totale wachttijd: {format_duration(total)}")
        await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.event
async def on_ready():
    logger.info(f"Bot actief als {bot.user}")
    try:
        synced = await bot.tree.sync()
        logger.info(f"Slash commands gesynchroniseerd: {len(synced)}")
    except Exception as e:
        logger.error(f"Fout bij slash command sync: {e}")


@bot.tree.command(name="controls", description="Laat bedieningsknoppen zien voor de muziek")
async def slash_controls(interaction: discord.Interaction):
    view = ControlButtons(interaction)
    await interaction.response.send_message("🎵 Muziekbediening:", view=view, ephemeral=True)


@bot.command(name="play")
async def play_command(ctx, *, query):
    await play(ctx, query=query)


@bot.tree.command(name="play", description="Speel een nummer af vanaf YouTube of Spotify")
@app_commands.describe(query="YouTube link, titel of Spotify-link")
async def slash_play(interaction: discord.Interaction, query: str):
    ctx = await commands.Context.from_interaction(interaction)
    ctx.author = interaction.user

    await interaction.response.defer(thinking=True)
    ctx.send = lambda content=None, *, embed=None: interaction.followup.send(content=content, embed=embed)

    await play(ctx, query=query)


async def play(ctx, query):
    if not ctx.author.voice:
        await ctx.send("Je moet eerst in een voicekanaal zitten.")
        return

    voice_channel = ctx.author.voice.channel
    if ctx.voice_client is None or not ctx.voice_client.is_connected():
        await voice_channel.connect()

    guild_id = ctx.guild.id
    get_queue(guild_id)

    queries = get_spotify_tracks(query) if is_spotify_url(query) else [query]
    songs = []
    for q in queries:
        tracks = await get_audio_info([q])
        flat_tracks = flatten_playlist(tracks)
        valid_tracks = filter_valid_tracks(flat_tracks)
        songs.extend(valid_tracks)

    if not songs:
        await ctx.send("Geen nummers gevonden.")
        return

    for song in songs:
        song['requester'] = str(ctx.author)

    add_to_queue(guild_id, songs)

    first_song = songs[0]
    embed = discord.Embed(title="🎶 Toegevoegd aan de wachtrij",
                          description=f"[{first_song['title']}]({first_song['webpage_url']})",
                          color=discord.Color.blue())
    embed.add_field(name="Duur", value=format_duration(first_song.get("duration", 0)), inline=True)
    embed.add_field(name="Aangevraagd door", value=str(ctx.author), inline=True)
    if first_song.get("thumbnail"):
        embed.set_thumbnail(url=first_song["thumbnail"])

    await ctx.send(embed=embed)

    if not ctx.voice_client.is_playing():
        await play_next(ctx)


async def play_next(ctx):
    guild_id = ctx.guild.id
    if not has_next(guild_id):
        await ctx.voice_client.disconnect()
        logger.info("Queue leeg, bot leavt voice.")
        return

    song = peek_next_song(guild_id)
    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'noplaylist': True,
        'extract_flat': False,
        'cookiefile': COOKIES_PATH
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(song['webpage_url'], download=False)
            stream_url = info.get('url')
            if not stream_url:
                raise Exception("Geen stream-URL gevonden")
    except Exception as e:
        logger.error(f"Kon stream URL niet ophalen: {e}")
        pop_next_song(guild_id)
        await play_next(ctx)
        return

    logger.info(f"Speelt af: {song['title']} - {stream_url}")
    source = get_ffmpeg_audio_source(stream_url)

    def after_playing(error):
        if error:
            logger.error(f"Fout tijdens afspelen: {error}")
        elif not ctx.voice_client or not ctx.voice_client.is_connected():
            logger.warning("Niet verbonden met voice bij einde nummer.")
        else:
            fut = asyncio.run_coroutine_threadsafe(handle_song_end(ctx), bot.loop)
            try:
                fut.result()
            except Exception as e:
                logger.error(f"Fout in after_playing: {e}")

    ctx.voice_client.play(source, after=after_playing)
    message = await send_now_playing(ctx, song)

    async def update_progress():
        elapsed = 0
        duration = song.get('duration') or 1
        while elapsed < duration and ctx.voice_client and ctx.voice_client.is_playing():
            await asyncio.sleep(5)
            elapsed += 5
            await update_progress_bar(message, song, elapsed)

    asyncio.create_task(update_progress())


async def handle_song_end(ctx):
    guild_id = ctx.guild.id
    if is_looping(guild_id):
        q = get_queue(guild_id)
        q.append(q.popleft())
    else:
        pop_next_song(guild_id)

    if has_next(guild_id):
        await play_next(ctx)
    else:
        await ctx.voice_client.disconnect()


@bot.command()
async def skip(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()
        await ctx.send("Nummer geskipt.")


@bot.command()
async def stop(ctx):
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await ctx.send("Muziek gestopt en kanaal verlaten.")


@bot.command()
async def np(ctx):
    song = peek_next_song(ctx.guild.id)
    if song:
        await send_now_playing(ctx, song)
    else:
        await ctx.send("Er wordt momenteel niets afgespeeld.")


@bot.command()
async def queue(ctx):
    q = get_queue(ctx.guild.id)
    if not q:
        await ctx.send("De wachtrij is leeg.")
        return

    embed = discord.Embed(title="Wachtrij", description="Aankomende nummers:")
    total = 0
    for i, song in enumerate(list(q)[:10], start=1):
        title = song['title']
        url = song['webpage_url']
        duration = format_duration(song.get('duration', 0))
        requester = song.get('requester', "Onbekend")
        total += song.get('duration', 0)

        embed.add_field(
            name=f"{i}. {title}",
            value=f"[Link]({url}) | Duur: {duration} | Door: {requester}",
            inline=False
        )

    embed.set_footer(text=f"Totale wachttijd: {format_duration(total)}")
    await ctx.send(embed=embed)


@bot.command()
async def clear(ctx):
    reset_queue(ctx.guild.id)
    await ctx.send("Wachtrij geleegd.")


@bot.command()
async def loop(ctx):
    state = toggle_looping(ctx.guild.id)
    await ctx.send(f"Looping staat nu op: {state}")


@bot.event
async def on_voice_state_update(member, before, after):
    voice_client = discord.utils.get(bot.voice_clients, guild=member.guild)
    if voice_client and voice_client.is_connected():
        if len(voice_client.channel.members) == 1:
            await voice_client.disconnect()
            logger.info(f"Voicekanaal verlaten in guild {member.guild.name} omdat het leeg was.")


bot.run(TOKEN)