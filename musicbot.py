import discord
from discord.ext import commands
import yt_dlp
import asyncio
import os
from dotenv import load_dotenv

# Laad de .env-variabelen (zoals DISCORD_TOKEN)
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='#', intents=intents)

queues = {}

ytdl_opts = {
    'format': 'bestaudio',
    'quiet': True,
    'noplaylist': True,
}

ytdl = yt_dlp.YoutubeDL(ytdl_opts)

@bot.event
async def on_ready():
    print(f'✅ Bot actief als {bot.user}')

def play_next(ctx):
    if queues[ctx.guild.id]:
        source = queues[ctx.guild.id].pop(0)
        ctx.voice_client.play(source, after=lambda e: play_next(ctx))

def add_to_queue(ctx, source):
    if ctx.guild.id in queues:
        queues[ctx.guild.id].append(source)
    else:
        queues[ctx.guild.id] = [source]

@bot.command()
async def join(ctx):
    if ctx.author.voice:
        await ctx.author.voice.channel.connect()
        await ctx.send("🎤 Bot is joined.")
    else:
        await ctx.send("❌ Je zit niet in een voice channel.")

@bot.command()
async def play(ctx, *, zoekterm):
    async with ctx.typing():
        info = ytdl.extract_info(f"ytsearch:{zoekterm}", download=False)['entries'][0]
        url = info['url']
        title = info['title']
        source = await discord.FFmpegOpusAudio.from_probe(url)
        add_to_queue(ctx, source)

        if not ctx.voice_client.is_playing():
            ctx.voice_client.play(source, after=lambda e: play_next(ctx))
            await ctx.send(f"🎶 Nu afspelen: **{title}**")
        else:
            await ctx.send(f"📥 Toegevoegd aan wachtrij: **{title}**")

@bot.command()
async def skip(ctx):
    ctx.voice_client.stop()
    await ctx.send("⏭️ Geskipt.")

@bot.command()
async def pause(ctx):
    ctx.voice_client.pause()
    await ctx.send("⏸️ Gepauzeerd.")

@bot.command()
async def resume(ctx):
    ctx.voice_client.resume()
    await ctx.send("▶️ Hervat.")

@bot.command()
async def leave(ctx):
    await ctx.voice_client.disconnect()
    await ctx.send("👋 Bot heeft voice channel verlaten.")

bot.run(TOKEN)