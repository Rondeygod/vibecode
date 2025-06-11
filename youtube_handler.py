# youtube_handler.py

import yt_dlp
import logging
from playlist_handler import flatten_playlist

logger = logging.getLogger(__name__)

COOKIES_PATH = "cookies.txt"

def get_audio_info(queries):
    if isinstance(queries, str):
        queries = [queries]
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
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        for q in queries:
            try:
                info = ydl.extract_info(q, download=False)

                if info is None:
                    continue

                if 'entries' in info and isinstance(info['entries'], list):
                    entries = flatten_playlist(info['entries'])
                    for entry in entries:
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
                logger.warning(f"[YT-DLP] Kan '{q}' niet verwerken: {e}")
    return results

def fetch_stream_url(video_url):
    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'noplaylist': True,
        'cookiefile': COOKIES_PATH,
        'source_address': '0.0.0.0'
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(video_url, download=False)
        return info.get('url')
