from collections import deque

# Opslag per guild
queue_map = {}        # guild_id → deque van songs
looping_map = {}      # guild_id → bool


def get_queue(guild_id):
    """
    Geeft de wachtrij van de opgegeven guild terug.
    Maakt er een lege deque van als deze nog niet bestaat.
    """
    return queue_map.setdefault(guild_id, deque())


def reset_queue(guild_id):
    """
    Leegt de wachtrij en zet looping uit voor de opgegeven guild.
    """
    queue_map[guild_id] = deque()
    looping_map[guild_id] = False


def add_to_queue(guild_id, songs):
    """
    Voegt een lijst van songs toe aan de wachtrij.
    """
    get_queue(guild_id).extend(songs)


def pop_next_song(guild_id):
    """
    Haalt het eerstvolgende nummer uit de wachtrij en verwijdert het.
    """
    q = get_queue(guild_id)
    return q.popleft() if q else None


def peek_next_song(guild_id):
    """
    Geeft het eerstvolgende nummer terug zonder het te verwijderen.
    """
    q = get_queue(guild_id)
    return q[0] if q else None


def is_looping(guild_id):
    """
    Retourneert True als looping actief is voor deze guild.
    """
    return looping_map.get(guild_id, False)


def toggle_looping(guild_id):
    """
    Zet looping aan/uit voor deze guild en retourneert de nieuwe status.
    """
    current = looping_map.get(guild_id, False)
    looping_map[guild_id] = not current
    return looping_map[guild_id]


def has_next(guild_id):
    """
    Retourneert True als er nummers in de wachtrij staan.
    """
    return bool(get_queue(guild_id))


def queue_length(guild_id):
    """
    Geeft het totale aantal nummers in de wachtrij terug.
    """
    return len(get_queue(guild_id))


def get_total_duration(guild_id):
    """
    Berekent de resterende tijd (in seconden) van de wachtrij,
    exclusief het nummer dat momenteel speelt.
    """
    q = get_queue(guild_id)
    # Sla het eerste nummer over (momenteel afgespeeld)
    return sum(song.get('duration', 0) for song in list(q)[1:])