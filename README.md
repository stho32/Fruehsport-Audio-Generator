# Fruehsport-Audio

Konvertiert Markdown-Skripte zu gesprochenen MP3-Audiodateien mit OpenAI Text-to-Speech.

Ideal für Frühsport-Anleitungen, Haushalts-Routinen oder andere geführte Audio-Programme.

## Demo

**[Audio anhören (4:51)](https://github.com/stho32/Fruehsport-Audio-Generator/raw/main/Skripte/fruehsport-basis-5min.mp3)** | [Skript ansehen](Skripte/fruehsport-basis-5min.md)

## Features

- **Text-to-Speech** via OpenAI API (Stimme: nova)
- **Pausen** mit `#PAUSE X` (X Sekunden Stille)
- **Audio einbinden** mit `#INCLUDE datei.mp3`
- **Materiallisten** vor `#START` werden ignoriert
- **Automatische Chunk-Aufteilung** für lange Texte
- **Parallele API-Anfragen** für schnelle Verarbeitung

## Voraussetzungen

- [uv](https://docs.astral.sh/uv/) (Python Package Manager)
- [ffmpeg](https://ffmpeg.org/) (Audio-Verarbeitung)
- OpenAI API-Key als `OPENAI_API_KEY` Umgebungsvariable

## Verwendung

```bash
uv run Apps/fruehsport-audio.py
```

Das Script findet automatisch alle `.md` Dateien in `Skripte/` ohne zugehörige `.mp3` und konvertiert sie.

## Skript-Format

```markdown
# Mein Programm

Materialliste (wird ignoriert):
- Item 1
- Item 2

#START

Willkommen! Wir beginnen mit der ersten Übung.

#PAUSE 5

Arme nach oben strecken.

#PAUSE 30

Sehr gut! Nächste Übung...

#INCLUDE entspannungsmusik.mp3
```

### Direktiven

| Direktive | Beschreibung |
|-----------|--------------|
| `#START` | Markiert den Beginn des gesprochenen Teils. Alles davor (z.B. Materiallisten) wird ignoriert. |
| `#PAUSE X` | Fügt X Sekunden Stille ein. |
| `#INCLUDE datei.mp3` | Bindet eine externe MP3-Datei ein. |

## Podcast-Player

`Apps/podcast-player.py` spielt lokale MP3s als eine Playlist ab — reines Abspielen,
ohne Eingriffe in Lautstärken. Sollen andere Quellen (z. B. Spotify) leiser laufen,
senkt man sie manuell ab, etwa per `~/.claude/scripts/spotify-ducking.sh`.

```bash
# Dateien und/oder Ordner (Ordner: enthaltene *.mp3 alphabetisch)
uv run Apps/podcast-player.py folge1.mp3 folge2.mp3 ~/Podcasts/heute/
```

- Player-Backend: mpv (Default), mplayer als Fallback
- Abspiel-Log: `Logs/podcast-player.jsonl` (eine JSON-Zeile je start/ende/abbruch/fehler)
- Ctrl+C/SIGTERM: Wiedergabe stoppt sauber (Exit 130/143)
- Details: `Anforderungen/R00002-podcast-player-cli.md`, `Anforderungen/R00003-ducking-aus-player-entfernen.md`, ADRs unter `Dokumentation/ADRs/`
- Tests: `uv run --with pytest --with pytest-cov python -m pytest Tests --cov=Apps`

## Projektstruktur

```
├── Apps/
│   ├── fruehsport-audio.py    # Hauptanwendung (TTS-Generator)
│   ├── podcast-player.py      # Podcast-Player CLI (R00002)
│   └── podcast_player.py      # Kernmodul des Players (importierbar/testbar)
├── Skripte/
│   ├── *.md                   # Eingabe-Skripte
│   └── *.mp3                  # Generierte Audio-Dateien
├── Tests/                     # Test-Pyramide (Unit, Integration, E2E)
├── Anforderungen/             # Spezifikationen
├── Dokumentation/ADRs/        # Architektur-Entscheidungen
├── Logs/                      # Abspiel-Log des Players (gitignored)
└── Musik/                     # Hintergrundmusik (optional, gitignored)
```

## Tipps

**Hintergrundmusik untermischen:**

```bash
ffmpeg -i skript.mp3 -i musik.wav \
  -filter_complex "[1:a]volume=0.1[m];[0:a][m]amix=inputs=2:duration=first[out]" \
  -map "[out]" skript-mit-musik.mp3
```

## Lizenz

MIT
