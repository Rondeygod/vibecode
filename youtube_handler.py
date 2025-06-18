import logging
import asyncio
import yt_dlp
import aiohttp
import os
from playlist_handler import flatten_playlist
from urllib.parse import parse_qs, urlparse
import re

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

COOKIES_PATH = "cookies.txt"
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
YOUTUBE_PLAYLIST_API_URL = "https://www.googleapis.com/youtube/v3/playlistItems"

print("API KEY GEVONDEN:", YOUTUBE_API_KEY)

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

                entries = []
                if 'entries' in info and isinstance(info['entries'], list):
                    entries = flatten_playlist(info['entries'])
                else:
                    entries = [info]

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

            except Exception as e:
                logger.warning(f"[YT-DLP] Fout bij verwerken van query '{q}': {e.__class__.__name__} - {e}")

    return results

async def get_playlist_video_urls(playlist_id: str, max_results: int = 500):
    if not YOUTUBE_API_KEY:
        logger.warning("[YOUTUBE API] Geen API-key gevonden in .env bestand.")
        return []

    if playlist_id.startswith("RD"):
        logger.warning("[YOUTUBE API] RD-playlist gedetecteerd. Alleen eerste video gebruiken.")
        return []

    async with aiohttp.ClientSession() as session:
        urls = []
        next_page_token = None

        while True:
            params = {
                'part': 'snippet',
                'playlistId': playlist_id,
                'maxResults': min(50, max_results - len(urls)),
                'key': YOUTUBE_API_KEY
            }
            if next_page_token:
                params['pageToken'] = next_page_token

            url_debug = f"{YOUTUBE_PLAYLIST_API_URL}?{'&'.join(f'{k}={v}' for k, v in params.items())}"
            logger.debug(f"[YOUTUBE API] API-aanroep: {url_debug}")

            async with session.get(YOUTUBE_PLAYLIST_API_URL, params=params) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.warning(f"[YOUTUBE API] Mislukte API-call: {resp.status} | Body: {body}")
                    break

                data = await resp.json()
                for item in data.get('items', []):
                    video_id = item['snippet'].get('resourceId', {}).get('videoId')
                    if video_id:
                        urls.append(f"https://www.youtube.com/watch?v={video_id}")
                    if len(urls) >= max_results:
                        break

                next_page_token = data.get('nextPageToken')
                if not next_page_token or len(urls) >= max_results:
                    break

    return urls

async def extract_playlist_id(playlist_url: str):
    parsed = urlparse(playlist_url)
    query = parse_qs(parsed.query)
    playlist_id = query.get("list", [None])[0]

    if not playlist_id:
        match = re.search(r"list=([a-zA-Z0-9_-]+)", playlist_url)
        if match:
            playlist_id = match.group(1)

    return playlist_id

async def get_audio_info_fast(playlist_url):
    playlist_id = await extract_playlist_id(playlist_url)

    if not playlist_id:
        logger.warning("[YOUTUBE API] Kan playlist-ID niet vinden in URL")
        return [], []

    if playlist_id.startswith("RD"):
        logger.warning("[YOUTUBE API] RD-playlist gedetecteerd. Alleen eerste video ophalen.")
        single_result = await get_audio_info([playlist_url])
        if not single_result:
            return [], []
        return single_result[:1], []

    urls = await get_playlist_video_urls(playlist_id)

    if not urls:
        logger.debug("[YOUTUBE API] Geen URLs via API. Fallback naar yt-dlp enkele video extractie.")
        single_result = await get_audio_info([playlist_url])
        if not single_result:
            return [], []
        return single_result[:1], []

    results = await get_audio_info(urls)
    if not results:
        return [], []

    first = results[:1]
    rest = results[1:]
    return first, rest