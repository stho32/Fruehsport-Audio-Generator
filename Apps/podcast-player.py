#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

"""podcast-player: CLI-Einstieg fuer den Podcast-Player mit Spotify-Ducking.

Verwendung:
    uv run Apps/podcast-player.py <datei.mp3|ordner> [weitere ...] [--level PROZENT]

Anforderung: R00002 — die Implementierung liegt im importierbaren Modul
``podcast_player.py`` im selben Verzeichnis (testbar ohne Subprozess).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from podcast_player import main

if __name__ == "__main__":
    sys.exit(main())
