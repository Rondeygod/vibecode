# Discord Music Bot

Een simpele Discord muziekbot met `#` als prefix. Je kunt `#play`, `#skip`, `#pause` en andere commando's gebruiken. De bot draait bijvoorbeeld op een Raspberry Pi.

## Installatie
1. Installeer Python, pip en FFmpeg.
   sudo apt install python3 python3-pip -y
   sudo apt install ffmpeg -y

2. Installeer de vereiste packages:
   ```bash
   pip install -r requirements.txt
   ```
3. Zet de nodige omgevingsvariabelen voor Discord en Spotify:
   - `DISCORD_TOKEN` voor je bot-token.
   - `SPOTIFY_CLIENT_ID` en `SPOTIFY_CLIENT_SECRET` voor Spotify (optioneel).
4. Start de bot met:
   ```bash
   python3 musicbot.py
   ```

