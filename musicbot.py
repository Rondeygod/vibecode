import discord
from discord.ext import commands, tasks
import yt_dlp
import asyncio
import os
from dotenv import load_dotenv
from datetime import timedelta

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='#', intents=intents)

queue = {}
looping = {}

def format_duration(seconds):
    return str(timedelta(seconds=int(seconds)))

def get_audio_info(query):
    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'default_search': 'ytsearch',
        'noplaylist': False,
        'extract_flat': False,
        'ignoreerrors': True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(query, download=False)
            if 'entries' in info:
                return [entry for entry in info['entries'] if entry]
            return [info]
        except Exception as e:
            print(f"[FOUT]: {e}")
            return []

@bot.event
async def on_ready():
    print(f"Bot actief als {bot.user}")

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return

    voice_client = discord.utils.get(bot.voice_clients, guild=member.guild)
    if voice_client and voice_client.channel and len(voice_client.channel.members) == 1:
        await voice_client.disconnect()

async def play_next(ctx):
    guild_id = ctx.guild.id
    voice_client = ctx.voice_client

    if guild_id not in queue or not queue[guild_id]:
        await voice_client.disconnect()
        return

    current = queue[guild_id][0]
    source = discord.FFmpegPCMAudio(current['url'], before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5")

    def after_playing(e):
        if e:
            print(f"Fout bij afspelen: {e}")
        coro = play_next(ctx)
        fut = asyncio.run_coroutine_threadsafe(coro, bot.loop)
        try:
            fut.result()
        except Exception as e:
            print(e)

    voice_client.play(source, after=after_playing if not looping.get(guild_id, False) else lambda e: voice_client.play(source, after=after_playing))

    if not looping.get(guild_id, False):
        queue[guild_id].pop(0)

    now_playing_index = 1 if not looping.get(guild_id, False) else 0
    total_tracks = len(queue[guild_id]) + 1
    remaining_duration = sum(float(song.get('duration', 0)) for song in queue[guild_id])

    embed = discord.Embed(
        title="Now Playing",
        description=f"{current['title']}",
        color=discord.Color.blue()
    )
    embed.add_field(name="Track", value=f"{now_playing_index}/{total_tracks}")
    embed.add_field(name="Duur", value=format_duration(current.get('duration', 0)))
    embed.add_field(name="Queue Resterend", value=format_duration(remaining_duration))
    if current.get("thumbnail"):
        embed.set_thumbnail(url=current["thumbnail"])
    await ctx.send(embed=embed)

@bot.command()
async def play(ctx, *, query):
    if not ctx.author.voice:
        await ctx.send("Je zit niet in een voicekanaal.")
        return

    try:
        await ctx.author.voice.channel.connect()
    except discord.ClientException:
        pass  # already connected

    songs = get_audio_info(query)
    if not songs:
        await ctx.send("Geen nummers gevonden.")
        return

    guild_id = ctx.guild.id
    if guild_id not in queue:
        queue[guild_id] = []

    for song in songs:
        queue[guild_id].append({
            'title': song.get('title'),
            'url': song.get('url'),
            'thumbnail': song.get('thumbnail'),
            'duration': song.get('duration', 0)
        })

    if not ctx.voice_client.is_playing():
        await play_next(ctx)
    else:
        await ctx.send(f"Toegevoegd aan wachtrij: {songs[0].get('title')}")

@bot.command()
async def playlist(ctx, *, query):
    if not ctx.author.voice:
        await ctx.send("Je zit niet in een voicekanaal.")
        return

    try:
        await ctx.author.voice.channel.connect()
    except discord.ClientException:
        pass  # already connected


    songs = get_audio_info(query)
    if not songs:
        await ctx.send("Geen nummers gevonden.")
        return

    guild_id = ctx.guild.id
    if guild_id not in queue:
        queue[guild_id] = []

    added = 0
    for song in songs:
        if song and song.get('url'):
            queue[guild_id].append({
                'title': song.get('title'),
                'url': song.get('url'),
                'thumbnail': song.get('thumbnail'),
                'duration': song.get('duration', 0)
            })
            added += 1

    await ctx.send(f"{added} nummers toegevoegd aan de wachtrij.")

    if not ctx.voice_client.is_playing():
        await play_next(ctx)

@bot.command()
async def skip(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()
        await ctx.send("Nummer overgeslagen.")
    else:
        await ctx.send("Er speelt momenteel niets af.")

@bot.command()
async def clear(ctx):
    guild_id = ctx.guild.id
    if guild_id in queue:
        queue[guild_id].clear()
        await ctx.send("Wachtrij is leeggemaakt.")

@bot.command()
async def loop(ctx):
    guild_id = ctx.guild.id
    current_state = looping.get(guild_id, False)
    looping[guild_id] = not current_state
    status = "aangezet" if not current_state else "uitgezet"
    await ctx.send(f"Loop is {status}.")

bot.run(TOKEN)