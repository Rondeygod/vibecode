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
                        if not entry or not entry.get("url"):
                            continue
                        results.append({
                            'title': entry.get('title', 'Onbekend'),
                            'url': entry.get('url') or f"https://www.youtube.com/watch?v={entry.get('id')}",
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
                logger.warning(f"[YT-DLP] Fout bij verwerken van query '{q}': {e.__class__.__name__} - {e}")

    return results

async def get_audio_info_fast(playlist_url):
    loop = asyncio.get_event_loop()
    flat_opts = {
        'quiet': True,
        'extract_flat': True,
        'force_generic_extractor': True,
        'noplaylist': False,
        'cookiefile': COOKIES_PATH,
        'ignoreerrors': True
    }

    try:
        with yt_dlp.YoutubeDL(flat_opts) as ydl:
            info = await loop.run_in_executor(None, lambda: ydl.extract_info(playlist_url, download=False))
            entries = info.get("entries", []) if info else []
            if not entries or not isinstance(entries, list):
                logger.warning(f"[YT-DLP] Ongeldige playliststructuur voor URL: {playlist_url}")
                return [], []

        # Detail ophalen van de eerste 3 entries
        detail_count = min(3, len(entries))
        first_tracks = []
        full_opts = {
            'quiet': True,
            'cookiefile': COOKIES_PATH,
            'ignoreerrors': True
        }
        with yt_dlp.YoutubeDL(full_opts) as ydl_full:
            for entry in entries[:detail_count]:
                try:
                    vid_id = entry.get("id")
                    if not vid_id:
                        continue
                    full = await loop.run_in_executor(None, lambda: ydl_full.extract_info(vid_id, download=False))
                    first_tracks.append({
                        'title': full.get('title', 'Onbekend'),
                        'url': full.get('url') or full.get('webpage_url'),
                        'webpage_url': full.get('webpage_url'),
                        'duration': full.get('duration', 0),
                        'thumbnail': full.get('thumbnail'),
                    })
                except Exception as e:
                    logger.warning(f"[YT-DLP] Fout bij ophalen detail track: {e}")

        # Rest als placeholders
        rest_tracks = []
        for entry in entries[detail_count:]:
            vid = entry.get("id")
            if not vid:
                continue
            rest_tracks.append({
                'title': entry.get('title', 'Onbekend'),
                'url': f"https://www.youtube.com/watch?v={vid}",
                'webpage_url': f"https://www.youtube.com/watch?v={vid}",
                'duration': 0,
                'thumbnail': None,
            })

        return first_tracks, rest_tracks

    except Exception as e:
        logger.warning(f"[YT-DLP] Playlist extractie mislukt: {e.__class__.__name__} - {e}")
        return [], []