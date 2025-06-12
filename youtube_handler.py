import yt_dlp
import logging
from playlist_handler import flatten_playlist

logger = logging.getLogger(__name__)

COOKIES_PATH = "cookies.txt"

base_opts = {
    'format': 'bestaudio/best',
    'quiet': True,
    'default_search': 'ytsearch',
    'noplaylist': False,
    'extract_flat': False,
    'ignoreerrors': True,
    'source_address': '0.0.0.0',
    'cookiefile': COOKIES_PATH
}


def get_audio_info(queries):
    """Zoekt naar YouTube-informatie voor een lijst van zoekopdrachten of URL's."""
    results = []

    with yt_dlp.YoutubeDL(base_opts) as ydl:
        for q in queries:
            try:
                info = ydl.extract_info(q, download=False)
                if not info:
                    logger.warning(f"[YT-DLP] Geen info gevonden voor: {q}")
                    continue

                entries = info['entries'] if 'entries' in info else [info]
                for entry in flatten_playlist(entries):
                    results.append({
                        'title': entry.get('title', 'Onbekend'),
                        'url': entry.get('url') or entry.get('webpage_url'),
                        'webpage_url': entry.get('webpage_url'),
                        'duration': entry.get('duration', 0),
                        'thumbnail': entry.get('thumbnail'),
                    })

            except Exception as e:
                logger.warning(f"[YT-DLP] Kan '{q}' niet verwerken: {e}")

    return results


def fetch_stream_url(video_url):
    """Haalt de directe audiostream-URL op van een YouTube-video."""
    opts = base_opts.copy()
    opts.update({
        'noplaylist': True,
        'extract_flat': False
    })

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            return info.get('url')
    except Exception as e:
        logger.error(f"[YT-DLP] Kan stream URL niet ophalen voor {video_url}: {e}")
        return None