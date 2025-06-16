import logging
import asyncio
import yt_dlp
from playlist_handler import flatten_playlist

logger = logging.getLogger(__name__)

COOKIES_PATH = "cookies.txt"

async def get_audio_info(queries):
    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'default_search': 'ytsearch',
        'noplaylist': False,
        'extract_flat': False,
        'ignoreerrors': True,
        'source_address': '0.0.0.0',
        'cookiefile': COOKIES_PATH
    }

    results = []

    loop = asyncio.get_event_loop()

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        for q in queries:
            try:
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(q, download=False))
                if info is None:
                    logger.warning(f"[YT-DLP] Geen info gevonden voor: {q}")
                    continue

                if 'entries' in info and isinstance(info['entries'], list):
                    entries = flatten_playlist(info['entries'])
                    for entry in entries:
                        if entry and entry.get("url"):
                            results.append({
                                'title': entry.get('title', 'Onbekend'),
                                'url': entry.get('url') or entry.get('webpage_url'),
                                'webpage_url': entry.get('webpage_url'),
                                'duration': entry.get('duration', 0),
                                'thumbnail': entry.get('thumbnail'),
                            })
                else:
                    results.append({
                        'title': info.get('title', 'Onbekend'),
                        'url': info.get('url') or info.get('webpage_url'),
                        'webpage_url': info.get('webpage_url'),
                        'duration': info.get('duration', 0),
                        'thumbnail': info.get('thumbnail'),
                    })

            except Exception as e:
                logger.warning(f"[YT-DLP] Kan '{q}' niet verwerken: {e}")

    return results

async def get_audio_info_fast(playlist_url):
    loop = asyncio.get_event_loop()
    # Stap 1: Snel alle video-IDs ophalen
    ydl_opts_flat = {
        'extract_flat': True,
        'quiet': True,
        'noplaylist': False,
        'ignoreerrors': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts_flat) as ydl:
        info = await loop.run_in_executor(None, lambda: ydl.extract_info(playlist_url, download=False))
        entries = info.get('entries', [])
        if not entries:
            return [], []
        # Stap 2: Eerste video volledig ophalen
        first_id = entries[0]['id']
        ydl_opts_full = {'quiet': True}
        with yt_dlp.YoutubeDL(ydl_opts_full) as ydl_full:
            first_info = await loop.run_in_executor(None, lambda: ydl_full.extract_info(first_id, download=False))
        # Bouw eerste nummer-dict
        first_track = {
            'title': first_info.get('title', 'Onbekend'),
            'url': first_info.get('url') or first_info.get('webpage_url'),
            'webpage_url': first_info.get('webpage_url'),
            'duration': first_info.get('duration', 0),
            'thumbnail': first_info.get('thumbnail'),
        }
        # De rest van de playlist als platte dicts (alleen id/titel)
        rest_tracks = []
        for entry in entries[1:]:
            if entry and entry.get("id"):
                rest_tracks.append({
                    'title': entry.get('title', 'Onbekend'),
                    'url': f"https://www.youtube.com/watch?v={entry['id']}",
                    'webpage_url': f"https://www.youtube.com/watch?v={entry['id']}",
                    'duration': 0,
                    'thumbnail': None,
                })
        return [first_track], rest_tracks