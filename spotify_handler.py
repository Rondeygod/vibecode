# spotify_handler.py

import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import os
from dotenv import load_dotenv
import logging

load_dotenv()
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")

logger = logging.getLogger(__name__)

sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
    client_id=SPOTIFY_CLIENT_ID,
    client_secret=SPOTIFY_CLIENT_SECRET
))

def is_spotify_url(url):
    return 'open.spotify.com' in url

def get_spotify_tracks(url):
    results = []
    try:
        if 'track' in url:
            track = sp.track(url)
            results.append(f"{track['artists'][0]['name']} - {track['name']}")
        elif 'playlist' in url:
            playlist_id = url.split("playlist/")[-1].split("?")[0]
            offset = 0
            while True:
                playlist = sp.playlist_items(playlist_id, offset=offset)
                for item in playlist['items']:
                    track = item['track']
                    results.append(f"{track['artists'][0]['name']} - {track['name']}")
                if playlist['next'] is None:
                    break
                offset += len(playlist['items'])
        elif 'album' in url:
            album_id = url.split("album/")[-1].split("?")[0]
            offset = 0
            while True:
                album = sp.album_tracks(album_id, offset=offset)
                for item in album['items']:
                    results.append(f"{item['artists'][0]['name']} - {item['name']}")
                if album['next'] is None:
                    break
                offset += len(album['items'])
    except Exception as e:
        logger.warning(f"Spotify fout: {e}")
    return results