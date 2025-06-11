# utils/queue_manager.py

from collections import deque

# Per-guild queue opslag
queue_map = {}
looping_map = {}

def get_queue(guild_id):
    """Geeft de queue terug voor een guild."""
    return queue_map.setdefault(guild_id, deque())

def reset_queue(guild_id):
    """Reset de queue en looping-status."""
    queue_map[guild_id] = deque()
    looping_map[guild_id] = False

def add_to_queue(guild_id, songs):
    """Voegt één of meerdere liedjes toe aan de wachtrij."""
    get_queue(guild_id).extend(songs)

def pop_next_song(guild_id):
    """Verwijdert en retourneert het eerstvolgende nummer in de wachtrij."""
    q = get_queue(guild_id)
    return q.popleft() if q else None

def peek_next_song(guild_id):
    """Geeft het eerstvolgende nummer terug zonder het te verwijderen."""
    q = get_queue(guild_id)
    return q[0] if q else None

def is_looping(guild_id):
    """Geeft aan of looping voor deze guild actief is."""
    return looping_map.get(guild_id, False)

def toggle_looping(guild_id):
    """Wisselt de looping-status om."""
    looping_map[guild_id] = not looping_map.get(guild_id, False)
    return looping_map[guild_id]

def has_next(guild_id):
    """Geeft aan of er meer nummers in de wachtrij zitten."""
    return bool(get_queue(guild_id))

def queue_length(guild_id):
    """Geeft het aantal nummers in de wachtrij."""
    return len(get_queue(guild_id))

def get_total_duration(guild_id):
    """Somt de resterende tijd van de wachtrij op."""
    q = get_queue(guild_id)
    return sum(s.get('duration', 0) for s in list(q)[1:])