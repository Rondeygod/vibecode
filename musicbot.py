import discord
from discord.ext import commands
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

@bot.event
async def on_ready():
    logger.info(f"Bot actief als {bot.user}")

@bot.command()
async def play(ctx, *, query):
    if not ctx.author.voice:
        await ctx.send("Je moet eerst in een voicekanaal zitten.")
        return

    voice_channel = ctx.author.voice.channel
    if ctx.voice_client is None:
        await voice_channel.connect()

    guild_id = ctx.guild.id
    get_queue(guild_id)

    if is_spotify_url(query):
        queries = get_spotify_tracks(query)
    else:
        queries = [query]

    songs = []
    for q in queries:
        tracks = get_audio_info(q)
        flat_tracks = flatten_playlist(tracks)
        valid_tracks = filter_valid_tracks(flat_tracks)
        songs.extend(valid_tracks)

    if not songs:
        await ctx.send("Geen nummers gevonden.")
        return

    # Voeg de aanvrager toe aan elk nummer
    for song in songs:
        song['requester'] = str(ctx.author)

    add_to_queue(guild_id, songs)

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

bot.run(TOKEN)