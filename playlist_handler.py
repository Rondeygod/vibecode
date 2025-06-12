def flatten_playlist(entries):
    """
    Zet een lijst met yt-dlp resultaten om naar een platte lijst van tracks.
    Gaat ook om met geneste playlist-structuren (zoals 'entries' binnen een playlist).
    """
    flat_tracks = []

    for item in entries:
        if not item or not isinstance(item, dict):
            continue

        nested_entries = item.get('entries')
        if nested_entries and isinstance(nested_entries, list):
            for sub in nested_entries:
                if sub and isinstance(sub, dict):
                    flat_tracks.append(sub)
        else:
            flat_tracks.append(item)

    return flat_tracks


def filter_valid_tracks(info_list):
    """
    Filtert tracks zonder geldige URL (zoals mislukte yt-dlp entries).
    """
    return [entry for entry in info_list if isinstance(entry, dict) and entry.get("url")]