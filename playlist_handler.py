# playlist_handler.py
def flatten_playlist(entries):
    """
    Neemt een lijst met yt-dlp resultaten (soms nested) en retourneert een platte lijst van tracks.
    """
    tracks = []
    for item in entries:
        if isinstance(item, dict) and 'entries' in item:
            for sub in item['entries']:
                if sub and isinstance(sub, dict):
                    tracks.append(sub)
        elif item and isinstance(item, dict):
            tracks.append(item)
    return tracks

def filter_valid_tracks(info_list):
    """
    Filter lege of foutieve tracks uit de lijst.
    """
    return [entry for entry in info_list if entry and entry.get("url")]