import discord
from discord.ext import commands
import yt_dlp
import asyncio
import os
import logging
import sys
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="[{asctime}] [{levelname:<8}] {message}",
    style="{"
)

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='#', intents=intents)

song_queues = {}
looping = {}

@bot.event
async def on_ready():
    logging.info(f"Bot actief als {bot.user}")

# Auto-leave als iedereen weg is
@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return
    voice_client = discord.utils.get(bot.voice_clients, guild=member.guild)
    if voice_client and voice_client.channel:
        if len(voice_client.channel.members) == 1:
            await voice_client.disconnect()
            logging.info(f"Bot verlaat voice channel {voice_client.channel.name} omdat deze leeg is")

def get_audio_info(query):
    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': False,
        'default_search': 'ytsearch',
        'noplaylist': False,
        'extract_flat': False,
        'ignoreerrors': True,
        'source_address': '0.0.0.0',
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            logging.info(f"Fetching info for: {query}")
            info = ydl.extract_info(query, download=False)

            if 'entries' in info:
                songs = []
                for entry in info['entries']:
                    if entry is None:
                        continue
                    songs.append({
                        'title': entry.get('title'),
                        'url': entry.get('url'),
                        'webpage_url': entry.get('webpage_url'),
                        'duration': entry.get('duration'),
                        'thumbnail': entry.get('thumbnail')
                    })
                logging.info(f"Gevonden playlist met {len(songs)} nummers.")
                return songs
            else:
                logging.info("Gevonden individueel nummer.")
                return [{
                    'title': info.get('title'),
                    'url': info.get('url'),
                    'webpage_url': info.get('webpage_url'),
                    'duration': info.get('duration'),
                    'thumbnail': info.get('thumbnail')
                }]
        except Exception as e:
            logging.error(f"Fout bij ophalen info: {e}")
            return []

async def play_next(ctx):
    guild_id = ctx.guild.id
    vc = ctx.voice_client

    if guild_id not in song_queues or len(song_queues[guild_id]) == 0:
        await vc.disconnect()
        logging.info("Queue leeg, bot leavt voice.")
        return

    current = song_queues[guild_id][0]
    source = discord.FFmpegPCMAudio(current['webpage_url'], before_options='-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5')

    def after_playing(err):
        if err:
            logging.error(f"Fout tijdens afspelen: {err}")
        if not looping.get(guild_id):
            song_queues[guild_id].pop(0)
        fut = asyncio.run_coroutine_threadsafe(play_next(ctx), bot.loop)
        try:
            fut.result()
        except Exception as e:
            logging.error(f"Fout na afspelen: {e}")

    vc.play(source, after=after_playing)

    # Embed info
    embed = discord.Embed(title="Now Playing", description=f"[{current['title']}]({current['webpage_url']})")
    if current.get('thumbnail'):
        embed.set_thumbnail(url=current['thumbnail'])
    
    current_index = 1
    total = len(song_queues[guild_id])
    remaining_duration = sum(track.get('duration') or 0 for track in song_queues[guild_id][1:])
    if current.get('duration'):
        embed.add_field(name="Duur huidig nummer", value=f"{current['duration']//60}:{current['duration']%60:02d}")
    embed.add_field(name="Track info", value=f"Nummer {current_index}/{total} | {remaining_duration//60}:{remaining_duration%60:02d} resterend")

    await ctx.send(embed=embed)

@bot.command(name='play')
async def play(ctx, *, query):
    if ctx.author.voice is None:
        await ctx.send("Je zit niet in een voicekanaal.")
        return

    voice_channel = ctx.author.voice.channel
    if ctx.voice_client is None or not ctx.voice_client.is_connected():
        await voice_channel.connect()

    songs = get_audio_info(query)
    if not songs:
        await ctx.send("Geen nummers gevonden.")
        return

    guild_id = ctx.guild.id
    if guild_id not in song_queues:
        song_queues[guild_id] = []

    song_queues[guild_id].extend(songs)
    await ctx.send(f"{len(songs)} nummer(s) toegevoegd.")

    if not ctx.voice_client.is_playing():
        await play_next(ctx)

@bot.command(name='skip')
async def skip(ctx):
    if ctx.voice_client is None or not ctx.voice_client.is_playing():
        await ctx.send("Er speelt nu niets.")
        return
    ctx.voice_client.stop()
    await ctx.send("Nummer overgeslagen.")

@bot.command(name='clear')
async def clear(ctx):
    guild_id = ctx.guild.id
    song_queues[guild_id] = []
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()
    await ctx.send("Wachtrij geleegd.")

@bot.command(name='loop')
async def loop(ctx):
    guild_id = ctx.guild.id
    looping[guild_id] = not looping.get(guild_id, False)
    await ctx.send(f"Loopmodus: {'aan' if looping[guild_id] else 'uit'}")

@bot.command(name='restart')
async def restart(ctx):
    await ctx.send("Herstarten...")
    logging.info("Script wordt herstart.")
    os.execv(sys.executable, [sys.executable] + sys.argv)

bot.run(TOKEN)
