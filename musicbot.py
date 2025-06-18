import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import logging
import os
from dotenv import load_dotenv

from youtube_handler import get_audio_info, get_audio_info_fast
from utils.queue_manager import add_to_queue, get_queue, reset_queue, pop_next_song
from utils.audio_utils import get_ffmpeg_audio_source

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="#", intents=intents)

logging.basicConfig(level=logging.INFO)

async def ensure_voice(interaction):
    if interaction.user.voice is None or interaction.user.voice.channel is None:
        await interaction.followup.send("Je moet in een voice channel zitten!")
        return None
    voice_channel = interaction.user.voice.channel
    if interaction.guild.voice_client is None:
        await voice_channel.connect()
    elif interaction.guild.voice_client.channel != voice_channel:
        await interaction.guild.voice_client.move_to(voice_channel)
    return interaction.guild.voice_client

async def play_next(interaction):
    queue = get_queue(interaction.guild.id)
    if not queue or len(queue) == 0:
        return  # Don't send a message here

    song = pop_next_song(interaction.guild.id)
    if not song:
        return

    stream_url = song.get("url") or song.get("webpage_url")
    if not stream_url:
        return

    voice_client = interaction.guild.voice_client
    if not voice_client or not voice_client.is_connected():
        voice_client = await ensure_voice(interaction)
        if not voice_client or not voice_client.is_connected():
            return

    try:
        source = get_ffmpeg_audio_source(stream_url)
    except Exception as e:
        logging.error(f"Fout bij het maken van audio bron: {e}")
        await play_next(interaction)
        return

    def after_playing(error):
        if error:
            logging.error(f"Fout bij afspelen: {error}")
        fut = asyncio.run_coroutine_threadsafe(play_next(interaction), bot.loop)
        try:
            fut.result()
        except Exception as e:
            logging.error(f"Fout bij play_next: {e}")

    try:
        voice_client.play(source, after=after_playing)
    except Exception as e:
        logging.error(f"Fout bij voice_client.play: {e}")
        await play_next(interaction)

@bot.tree.command(name="play", description="Speel een nummer, YouTube-link, playlist of zoekopdracht af.")
@app_commands.describe(query="YouTube-link, playlist of zoekopdracht")
async def slash_play(interaction: discord.Interaction, query: str):
    await interaction.response.defer(thinking=True)
    requester = interaction.user.display_name

    # YouTube playlist-link?
    if ("youtube.com/playlist" in query) or ("list=" in query and "youtube.com" in query):
        first_tracks, rest_tracks = await get_audio_info_fast(query)
        new_first_tracks = []
        for t in first_tracks:
            if isinstance(t, dict):
                t['requester'] = requester
                new_first_tracks.append(t)
            else:
                new_first_tracks.append({'title': str(t), 'url': str(t), 'webpage_url': str(t), 'duration': 0, 'thumbnail': None, 'requester': requester})
        first_tracks = new_first_tracks

        if first_tracks:
            add_to_queue(interaction.guild.id, first_tracks)
            await interaction.followup.send(f"Toegevoegd: {first_tracks[0]['title']}")
            voice_client = interaction.guild.voice_client
            if not voice_client or not voice_client.is_playing():
                await ensure_voice(interaction)
                await play_next(interaction)
        else:
            await interaction.followup.send("Geen nummers gevonden in deze YouTube-playlist.")

        # Voeg de rest toe in de achtergrond
        async def add_rest():
            new_rest_tracks = []
            for t in rest_tracks:
                if isinstance(t, dict):
                    t['requester'] = requester
                    new_rest_tracks.append(t)
                else:
                    new_rest_tracks.append({'title': str(t), 'url': str(t), 'webpage_url': str(t), 'duration': 0, 'thumbnail': None, 'requester': requester})
            if new_rest_tracks:
                add_to_queue(interaction.guild.id, new_rest_tracks)
        asyncio.create_task(add_rest())
        return

    # YouTube-link (geen playlist)
    if "youtube.com" in query or "youtu.be" in query:
        yt_tracks = await get_audio_info([query])
        for t in yt_tracks:
            t['requester'] = requester
        if yt_tracks:
            add_to_queue(interaction.guild.id, yt_tracks)
            await interaction.followup.send(f"Toegevoegd: {yt_tracks[0]['title']}")
            voice_client = interaction.guild.voice_client
            if not voice_client or not voice_client.is_playing():
                await ensure_voice(interaction)
                await play_next(interaction)
        else:
            await interaction.followup.send("Geen nummers gevonden.")
        return

    # Zoekopdracht (YouTube search)
    yt_tracks = await get_audio_info([query])
    for t in yt_tracks:
        t['requester'] = requester
    if yt_tracks:
        add_to_queue(interaction.guild.id, yt_tracks)
        await interaction.followup.send(f"Toegevoegd: {yt_tracks[0]['title']}")
        voice_client = interaction.guild.voice_client
        if not voice_client or not voice_client.is_playing():
            await ensure_voice(interaction)
            await play_next(interaction)
    else:
        await interaction.followup.send("Geen nummers gevonden.")

@bot.tree.command(name="skip", description="Sla het huidige nummer over.")
async def slash_skip(interaction: discord.Interaction):
    voice_client = interaction.guild.voice_client
    if voice_client and voice_client.is_playing():
        voice_client.stop()
        await interaction.response.send_message("Nummer overgeslagen!")
    else:
        await interaction.response.send_message("Er wordt momenteel niets afgespeeld.", ephemeral=True)

@bot.tree.command(name="clear", description="Leeg de wachtrij.")
async def slash_clear(interaction: discord.Interaction):
    reset_queue(interaction.guild.id)
    await interaction.response.send_message("De wachtrij is geleegd.")

@bot.tree.command(name="stop", description="Stop de muziek en disconnect.")
async def slash_stop(interaction: discord.Interaction):
    voice_client = interaction.guild.voice_client
    if voice_client:
        voice_client.stop()
        await voice_client.disconnect()
        reset_queue(interaction.guild.id)
        await interaction.response.send_message("Bot gestopt en gedisconnect.")
    else:
        await interaction.response.send_message("Bot is niet verbonden met een voice channel.", ephemeral=True)

@bot.tree.command(name="queue", description="Toon de wachtrij.")
async def slash_queue(interaction: discord.Interaction):
    queue = get_queue(interaction.guild.id)
    if not queue or len(queue) == 0:
        await interaction.response.send_message("De wachtrij is leeg.")
        return
    max_songs = 20
    msg = "**Wachtrij:**\n"
    for i, song in enumerate(queue[:max_songs], 1):
        msg += f"{i}. {song.get('title', 'Onbekend')} ({song.get('requester', 'Onbekend')})\n"
    if len(queue) > max_songs:
        msg += f"...en {len(queue) - max_songs} meer nummers in de wachtrij."
    await interaction.response.send_message(msg)

@bot.event
async def on_ready():
    print(f"Bot is online als {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Slash commands gesynchroniseerd: {len(synced)}")
    except Exception as e:
        print(f"Slash commands sync fout: {e}")

bot.run(TOKEN)