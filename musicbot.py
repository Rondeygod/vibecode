import discord
from discord.ext import commands
import yt_dlp
import asyncio
import os
from functools import partial
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='#', intents=intents)

queue = {}

@bot.event
async def on_ready():
    print(f"Bot actief als {bot.user}")

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return

    voice_client = discord.utils.get(bot.voice_clients, guild=member.guild)
    if voice_client and voice_client.channel:
        if len(voice_client.channel.members) == 1:
            await voice_client.disconnect()
            print(f"Bot verlaat voice kanaal {voice_client.channel.name} (leeg)")

def get_audio_info(query):
    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'default_search': 'auto',
        'noplaylist': False,
        'extract_flat': False,
        'ignoreerrors': True,
    }

    results = []
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(query, download=False)
        except Exception as e:
            print(f"[FOUT bij ophalen]: {e}")
            return []

        if info is None:
            return []

        if 'entries' in info:
            for entry in info['entries']:
                if not entry:
                    continue
                try:
                    if 'url' not in entry:
                        sub_info = ydl.extract_info(entry['webpage_url'], download=False)
                        results.append(sub_info)
                    else:
                        results.append(entry)
                except Exception as e:
                    print(f"[SKIP video]: {e}")
                    continue
        else:
            results.append(info)

    return results

async def play_next(ctx):
    guild_id = ctx.guild.id
    if queue.get(guild_id):
        song = queue[guild_id].pop(0)
        source = discord.FFmpegPCMAudio(song['url'])

        def after_playing(error):
            fut = asyncio.run_coroutine_threadsafe(play_next(ctx), bot.loop)
            try:
                fut.result()
            except Exception as e:
                print(f"[FOUT in after_playing]: {e}")

        ctx.voice_client.play(source, after=after_playing)

        embed = discord.Embed(title="🎶 Now playing", description=song['title'], color=0x1DB954)
        if song['thumbnail']:
            embed.set_thumbnail(url=song['thumbnail'])
        await ctx.send(embed=embed)
    else:
        await ctx.voice_client.disconnect()

@bot.command(name="play")
async def play(ctx, *, query):
    if not ctx.author.voice:
        await ctx.send("Je moet eerst in een voice channel zitten.")
        return

    if ctx.voice_client is None or not ctx.voice_client.is_connected():
        await ctx.author.voice.channel.connect()

    try:
        entries = get_audio_info(query)
    except Exception as e:
        await ctx.send(f"Fout bij ophalen audio: {e}")
        return

    if not entries:
        await ctx.send("Geen nummers gevonden.")
        return

    guild_id = ctx.guild.id
    if guild_id not in queue:
        queue[guild_id] = []

    for entry in entries:
        queue[guild_id].append({
            'title': entry.get('title', 'Onbekend'),
            'url': entry.get('url'),
            'thumbnail': entry.get('thumbnail')
        })

    if not ctx.voice_client.is_playing():
        await play_next(ctx)
    else:
        await ctx.send(f"Toegevoegd aan wachtrij: {entries[0].get('title', 'Onbekend')}")

@bot.command(name="skip")
async def skip(ctx):
    if ctx.voice_client is None or not ctx.voice_client.is_playing():
        await ctx.send("Er speelt nu niks.")
        return

    ctx.voice_client.stop()
    await ctx.send("Nummer geskipt.")

bot.run(TOKEN)