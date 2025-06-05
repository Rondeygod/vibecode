import discord
from discord.ext import commands
import yt_dlp
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='#', intents=intents)

queues = {}

ytdl_opts = {
    'format': 'bestaudio',
    'quiet': True,
    'noplaylist': False,
}

ytdl = yt_dlp.YoutubeDL(ytdl_opts)

@bot.event
async def on_ready():
    print(f'✅ Bot actief als {bot.user}')

def play_next(ctx):
    if queues.get(ctx.guild.id):
        if len(queues[ctx.guild.id]) > 0:
            next_source = queues[ctx.guild.id].pop(0)
            ctx.voice_client.play(next_source, after=lambda e: play_next(ctx))

def add_to_queue(ctx, source):
    if ctx.guild.id in queues:
        queues[ctx.guild.id].append(source)
    else:
        queues[ctx.guild.id] = [source]

@bot.command()
async def join(ctx):
    if ctx.author.voice:
        await ctx.author.voice.channel.connect()
        await ctx.send("✅ Bot is joined.")
    else:
        await ctx.send("❌ Je zit niet in een voice channel.")

@bot.command()
async def play(ctx, *, zoekterm):
    if not ctx.voice_client:
        if ctx.author.voice:
            await ctx.author.voice.channel.connect()
            await ctx.send("🔌 Bot is automatisch gejoined in je voicechannel.")
        else:
            await ctx.send("❌ Je zit zelf niet in een voicechannel.")
            return

    async with ctx.typing():
        try:
            zoekresultaat = ytdl.extract_info(zoekterm, download=False)
            entries = []

            if 'entries' in zoekresultaat:
                entries = zoekresultaat['entries']
                await ctx.send(f"📃 Playlist gevonden: {len(entries)} nummers worden toegevoegd.")
            else:
                entries = [zoekresultaat]

            for i, info in enumerate(entries):
                title = info.get('title')
                url = info.get('url')
                webpage_url = info.get('webpage_url', '')
                thumbnail = info.get('thumbnail', '')
                uploader = info.get('uploader', 'Onbekend')

                source = await discord.FFmpegOpusAudio.from_probe(url)
                add_to_queue(ctx, source)

                if i == 0:
                    embed = discord.Embed(
                        title="🎶 Now Playing" if not ctx.voice_client.is_playing() else "📥 Toegevoegd aan wachtrij",
                        description=f"[{title}]({webpage_url})",
                        color=discord.Color.blue()
                    )
                    if thumbnail:
                        embed.set_thumbnail(url=thumbnail)
                    embed.set_footer(text=f"Source: {uploader}")
                    await ctx.send(embed=embed)

            if not ctx.voice_client.is_playing():
                ctx.voice_client.play(queues[ctx.guild.id].pop(0), after=lambda e: play_next(ctx))
        except Exception as e:
            await ctx.send(f"❌ Fout bij afspelen: {str(e)}")

@bot.command()
async def skip(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()
        await ctx.send("⏭️ Geskipt.")
    else:
        await ctx.send("❌ Er is niets om te skippen.")

@bot.command()
async def pause(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.pause()
        await ctx.send("⏸️ Gepauzeerd.")
    else:
        await ctx.send("❌ Er is niets om te pauzeren.")

@bot.command()
async def resume(ctx):
    if ctx.voice_client and ctx.voice_client.is_paused():
        ctx.voice_client.resume()
        await ctx.send("▶️ Hervat.")
    else:
        await ctx.send("❌ Er is niets gepauzeerd.")

@bot.command()
async def leave(ctx):
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await ctx.send("👋 Bot heeft voice channel verlaten.")
    else:
        await ctx.send("❌ Ik zit niet in een voicechannel.")

@bot.event
async def on_voice_state_update(member, before, after):
    if not member.bot and before.channel and before.channel != after.channel:
        voice_client = discord.utils.get(bot.voice_clients, guild=member.guild)
        if voice_client and len(before.channel.members) == 1:
            await voice_client.disconnect()
            channel_name = before.channel.name
            text_channel = discord.utils.get(member.guild.text_channels, name="general")
            if text_channel:
                await text_channel.send(f"👋 Ik heb voicekanaal '{channel_name}' verlaten omdat iedereen weg was.")

bot.run(TOKEN)