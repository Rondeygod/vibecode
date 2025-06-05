import sys
import discord
from discord.ext import commands
import yt_dlp
import asyncio
import os
import logging
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")

# Logging instellen
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] [%(levelname)s] %(message)s')
logging.getLogger("yt_dlp").setLevel(logging.WARNING)

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='#', intents=intents)

queue = {}
looping = {}

# Spotify setup
sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
    client_id=SPOTIFY_CLIENT_ID,
    client_secret=SPOTIFY_CLIENT_SECRET
))

def is_spotify_url(url):
    return 'open.spotify.com' in url

def get_spotify_tracks(url):
    results = []
    if 'track' in url:
        track = sp.track(url)
        results.append(f"{track['artists'][0]['name']} - {track['name']}")
    elif 'playlist' in url:
        playlist = sp.playlist_tracks(url)
        for item in playlist['items']:
            track = item['track']
            results.append(f"{track['artists'][0]['name']} - {track['name']}")
    elif 'album' in url:
        album = sp.album_tracks(url)
        for item in album['items']:
            results.append(f"{item['artists'][0]['name']} - {item['name']}")
    return results

def format_duration(seconds):
    minutes = seconds // 60
    sec = seconds % 60
    return f"{minutes}:{sec:02d}"

def get_audio_info(query, first_only=False):
    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'default_search': 'ytsearch',
        'noplaylist': not first_only,
        'extract_flat': 'in_playlist' if first_only else False,
        'ignoreerrors': True,
        'source_address': '0.0.0.0',
        'logger': logging.getLogger("yt_dlp"),
        'outtmpl': '%(id)s.%(ext)s'
    }

    if is_spotify_url(query):
        queries = get_spotify_tracks(query)
    else:
        queries = [query]

    results = []
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        for q in queries:
            try:
                info = ydl.extract_info(q, download=False)
                entries = info.get('entries', [info])
                for entry in entries:
                    if not entry or not entry.get('url'):
                        logging.warning("Ongeldige of lege entry overgeslagen.")
                        continue
                    results.append({
                        'title': entry.get('title', 'Onbekend'),
                        'url': entry.get('url') or entry.get('webpage_url'),
                        'webpage_url': entry.get('webpage_url'),
                        'duration': entry.get('duration', 0),
                        'thumbnail': entry.get('thumbnail')
                    })
                    if first_only:
                        break
            except Exception as e:
                logging.warning(f"Fout bij ophalen info: {e}")
    return results

async def play_next(ctx):
    guild_id = ctx.guild.id
    if not queue[guild_id]:
        await ctx.voice_client.disconnect()
        logging.info("Queue leeg, bot leavt voice.")
        return

    song = queue[guild_id][0]
    logging.info(f"Speelt af: {song['title']} - {song['url']}")

    source = discord.FFmpegPCMAudio(song['webpage_url'], before_options='-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5')
    ctx.voice_client.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(handle_song_end(ctx), bot.loop))

    total_songs = len(queue[guild_id])
    remaining_time = sum(s.get('duration', 0) for s in queue[guild_id][1:])

    embed = discord.Embed(title="Now Playing", description=f"[{song['title']}]({song['webpage_url']})")
    embed.add_field(name="Duur huidig nummer", value=format_duration(song['duration']), inline=True)
    embed.add_field(name="Track info", value=f"Nummer 1/{total_songs} | {format_duration(remaining_time)} resterend", inline=True)
    if song.get('thumbnail'):
        embed.set_thumbnail(url=song['thumbnail'])

    await ctx.send(embed=embed)

async def handle_song_end(ctx):
    guild_id = ctx.guild.id
    if looping.get(guild_id, False):
        queue[guild_id].append(queue[guild_id].pop(0))
    else:
        queue[guild_id].pop(0)

    if queue[guild_id]:
        await play_next(ctx)
    else:
        await ctx.voice_client.disconnect()

def reset_queue(guild_id):
    queue[guild_id] = []
    looping[guild_id] = False

@bot.event
async def on_ready():
    logging.info(f"Bot actief als {bot.user}")

@bot.command()
async def play(ctx, *, query):
    if not ctx.author.voice:
        await ctx.send("Je moet eerst in een voicekanaal zitten.")
        return

    voice_channel = ctx.author.voice.channel
    if ctx.voice_client is None:
        await voice_channel.connect()

    guild_id = ctx.guild.id
    if guild_id not in queue:
        reset_queue(guild_id)

    songs = get_audio_info(query, first_only=True)
    if not songs:
        await ctx.send("Geen nummers gevonden.")
        return

    queue[guild_id].extend(songs)
    if not ctx.voice_client.is_playing():
        await play_next(ctx)

    # Laad resterende tracks op achtergrond
    async def load_remaining():
        rest = get_audio_info(query, first_only=False)
        if len(rest) > 1:
            queue[guild_id].extend(rest[1:])
    asyncio.create_task(load_remaining())

@bot.command()
async def skip(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()
        await ctx.send("Nummer geskipt.")

@bot.command()
async def clear(ctx):
    reset_queue(ctx.guild.id)
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()
    await ctx.send("Wachtrij geleegd.")

@bot.command()
async def loop(ctx):
    guild_id = ctx.guild.id
    looping[guild_id] = not looping.get(guild_id, False)
    await ctx.send(f"Looping staat nu op: {looping[guild_id]}")

@bot.command()
async def restart(ctx):
    await ctx.send("Bot herstart...")
    logging.info("Script wordt herstart.")
    os.execv(sys.executable, ['python'] + sys.argv)

bot.run(TOKEN)
