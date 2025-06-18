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

class PlayerControls(discord.ui.View):
    def __init__(self, interaction):
        super().__init__(timeout=None)
        self.interaction = interaction

    @discord.ui.button(label="⏭️ Skip", style=discord.ButtonStyle.primary)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.stop()
            await interaction.response.send_message("Nummer overgeslagen!", ephemeral=True)
        else:
            await interaction.response.send_message("Er wordt niets afgespeeld.", ephemeral=True)

    @discord.ui.button(label="⏹️ Stop", style=discord.ButtonStyle.danger)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc:
            vc.stop()
            await vc.disconnect()
            reset_queue(interaction.guild.id)
            await interaction.response.send_message("Bot gestopt en gedisconnect.", ephemeral=True)
        else:
            await interaction.response.send_message("Bot is niet verbonden.", ephemeral=True)

    @discord.ui.button(label="📜 Queue", style=discord.ButtonStyle.secondary)
    async def queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        queue = get_queue(interaction.guild.id)
        if not queue:
            await interaction.response.send_message("De wachtrij is leeg.", ephemeral=True)
            return
        embed = discord.Embed(title="🎶 Wachtrij", color=discord.Color.blue())
        for i, song in enumerate(queue[:20], 1):
            embed.add_field(name=f"{i}. {song.get('title', 'Onbekend')}", value=f"Gevraagd door: {song.get('requester', 'Onbekend')}", inline=False)
        if len(queue) > 20:
            embed.set_footer(text=f"...en {len(queue) - 20} meer nummers in de wachtrij.")
        await interaction.response.send_message(embed=embed, ephemeral=True)


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
    if not queue:
        return

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
    try:
        if "playlist" in query or ("list=" in query and "youtube.com" in query):
            first_tracks, rest_tracks = await get_audio_info_fast(query)
            for t in first_tracks:
                t['requester'] = requester
            add_to_queue(interaction.guild.id, first_tracks)
            await interaction.followup.send(f"Toegevoegd: {first_tracks[0]['title']}", view=PlayerControls(interaction))
            voice_client = interaction.guild.voice_client
            if not voice_client or not voice_client.is_playing():
                await ensure_voice(interaction)
                await play_next(interaction)

            async def add_rest():
                for t in rest_tracks:
                    t['requester'] = requester
                add_to_queue(interaction.guild.id, rest_tracks)
            asyncio.create_task(add_rest())
            return

        yt_tracks = await get_audio_info([query])
        for t in yt_tracks:
            t['requester'] = requester
        if yt_tracks:
            add_to_queue(interaction.guild.id, yt_tracks)
            await interaction.followup.send(f"Toegevoegd: {yt_tracks[0]['title']}", view=PlayerControls(interaction))
            voice_client = interaction.guild.voice_client
            if not voice_client or not voice_client.is_playing():
                await ensure_voice(interaction)
                await play_next(interaction)
        else:
            await interaction.followup.send("Geen nummers gevonden.")
    except Exception as e:
        logging.error(f"Fout bij get_audio_info: {e}")
        await interaction.followup.send("Er is een fout opgetreden bij het ophalen van audio-informatie.")


@bot.event
async def on_ready():
    print(f"Bot is online als {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Slash commands gesynchroniseerd: {len(synced)}")
    except Exception as e:
        print(f"Slash commands sync fout: {e}")

bot.run(TOKEN)