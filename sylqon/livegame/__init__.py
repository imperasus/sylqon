"""In-game overlay coach.

READ-ONLY integration with Riot's local **Live Client Data API**
(``https://127.0.0.1:2999/liveclientdata/*``). This package only ever performs
HTTP GETs against that localhost endpoint; it never writes to, injects into, or
automates input for the League client. All missions are derived from information
the player already sees on screen (CS, deaths, wards, objective events, timers).
"""
