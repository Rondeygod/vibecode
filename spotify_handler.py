import os
import logging
import spotipy
from dotenv import load_dotenv
from spotipy.oauth2 import SpotifyClientCredentials

load_dotenv()

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")

logger = logging.getLogger(__name__)

if SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET:
    sp = spotipy.Spotify(
        auth_manager=SpotifyClientCredentials(
            client_id=SPOTIFY_CLIENT_ID,
            client_secret=SPOTIFY_CLIENT_SECRET,
        )
    )
else:
    logger.warning(
        "SPOTIFY_CLIENT_ID/SECRET niet ingesteld. Spotify functionaliteit is uitgeschakeld."
    )
    sp = None

def is_spotify_url(url):
    """Controleert of de URL een Spotify-link is."""
    return 'open.spotify.com' in url

def extract_spotify_id(url, content_type):
    """Extraheert het ID uit een Spotify-URL voor een bepaald type (track/playlist/album)."""
    try:
        return url.split(f"{content_type}/")[-1].split("?")[0]
    except IndexError:
        return None

def get_spotify_tracks(url):
    """
    Zet een Spotify-track, playlist of album om naar een lijst van 'Artiest - Titel' strings.
    Wordt gebruikt voor YouTube-zoekopdrachten.
    """
    results = []

    if sp is None:
        logger.warning("Spotify client niet beschikbaar. Sla request over.")
        return results

    try:
        if 'track' in url:
            track = sp.track(url)
            results.append(f"{track['artists'][0]['name']} - {track['name']}")

        elif 'playlist' in url:
            playlist_id = extract_spotify_id(url, 'playlist')
            offset = 0
            while True:
                items = sp.playlist_items(playlist_id, offset=offset)
                for item in items.get('items', []):
                    track = item.get('track')
                    if track:
                        results.append(f"{track['artists'][0]['name']} - {track['name']}")
                if not items.get('next'):
                    break
                offset += len(items.get('items', []))

        elif 'album' in url:
            album_id = extract_spotify_id(url, 'album')
            offset = 0
            while True:
                items = sp.album_tracks(album_id, offset=offset)
                for track in items.get('items', []):
                    results.append(f"{track['artists'][0]['name']} - {track['name']}")
                if not items.get('next'):
                    break
                offset += len(items.get('items', []))

    except Exception as e:
        logger.warning(f"[Spotify] Fout bij ophalen tracks: {e}")

    return results