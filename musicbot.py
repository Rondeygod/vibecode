import discord
from discord.ext import commands
import yt_dlp
import asyncio
import os
import logging
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from dotenv import load_dotenv
import sys

# Load .env
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")

# Logging setup
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] [%(levelname)s] %(message)s')

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='#', intents=intents)

queue = {}
looping = {}

# Spotify setup
sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
    client_id=SPOTIFY_CLIENT_ID,
    client_secret=SPOTIFY_CLIENT_SECRET
))

# Detect Spotify
def is_spotify_url(url):
    return 'open.spotify.com' in url

def get_spotify_tracks(url):
    results = []
    try:
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
    except Exception as e:
        logging.error(f"Fout bij ophalen Spotify-tracks: {e}")
    return results

def format_duration(seconds):
    minutes = seconds // 60
    sec = seconds % 60
    return f"{minutes}:{sec:02d}"

def get_audio_info(query):
    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'default_search': 'ytsearch',
        'noplaylist': False,
        'extract_flat': False,
        'ignoreerrors': True,
        'source_address': '0.0.0.0',
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
                if 'entries' in info:
                    for entry in info['entries']:
                        if entry is None:
                            continue
                        results.append({
                            'title': entry.get('title', 'Onbekend'),
                            'url': entry.get('url') or entry.get('webpage_url'),
                            'webpage_url': entry.get('webpage_url'),
                            'duration': entry.get('duration', 0),
                            'thumbnail': entry.get('thumbnail', None)
                        })
                else:
                    results.append({
                        'title': info.get('title', 'Onbekend'),
                        'url': info.get('url') or info.get('webpage_url'),
                        'webpage_url': info.get('webpage_url'),
                        'duration': info.get('duration', 0),
                        'thumbnail': info.get('thumbnail', None)
                    })
            except Exception as e:
                logging.warning(f"[FOUT] Kan '{q}' niet verwerken: {e}")
    return results

async def play_next(ctx):
    guild_id = ctx.guild.id
    if not queue.get(guild_id):
        await ctx.voice_client.disconnect()
        logging.info("Queue leeg, bot leavt voice.")
        return

    current = queue[guild_id][0]
    logging.info(f"Speelt af: {current['title']} - {current['webpage_url']}")

    # Directe audiostream ophalen
    try:
        ydl_opts = {
            'format': 'bestaudio[ext=m4a]/bestaudio/best',
            'quiet': True,
            'default_search': 'ytsearch',
            'noplaylist': False,
            'extract_flat': False,
            'ignoreerrors': True,
            'source_address': '0.0.0.0',
            'http_headers': {
                'User-Agent': 'Mozilla/5.0',
                'Accept-Language': 'en-US,en;q=0.9',
            },
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(current['webpage_url'], download=False)
            audio_url = info['url']
    except Exception as e:
        logging.error(f"Fout bij ophalen audiostream: {e}")
        await ctx.send(f"Kon het nummer niet afspelen: {current['title']}")
        queue[guild_id].pop(0)
        await play_next(ctx)
        return

    source = discord.FFmpegPCMAudio(audio_url, before_options='-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5')
    ctx.voice_client.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(handle_song_end(ctx), bot.loop))

    total = len(queue[guild_id])
    remaining = sum(s.get('duration', 0) for s in queue[guild_id][1:])

    embed = discord.Embed(title="Now Playing", description=f"[{current['title']}]({current['webpage_url']})")
    embed.add_field(name="Duur huidig nummer", value=format_duration(current.get('duration', 0)), inline=True)
    embed.add_field(name="Track info", value=f"Nummer 1/{total} | {format_duration(remaining)} resterend", inline=True)
    if current.get('thumbnail'):
        embed.set_thumbnail(url=current['thumbnail'])

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

    songs = get_audio_info(query)
    if not songs:
        await ctx.send("Geen nummers gevonden.")
        return

    queue[guild_id].extend(songs)

    if not ctx.voice_client.is_playing():
        await play_next(ctx)

@bot.command()
async def skip(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()
        await ctx.send("Nummer geskipt.")

@bot.command()
async def clear(ctx):
    reset_queue(ctx.guild.id)
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