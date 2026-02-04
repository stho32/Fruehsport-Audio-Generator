# Fruehsport-Audio

Konvertiert Markdown-Skripte zu gesprochenen MP3-Audiodateien mit OpenAI Text-to-Speech.

Ideal für Frühsport-Anleitungen, Haushalts-Routinen oder andere geführte Audio-Programme.

## Demo

Hör dir das Beispiel an:

| Skript | Audio | Dauer |
|--------|-------|-------|
| [fruehsport-basis-5min.md](Skripte/fruehsport-basis-5min.md) | [fruehsport-basis-5min.mp3](Skripte/fruehsport-basis-5min.mp3) | 4:51 |

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

## Projektstruktur

```
├── Apps/
│   └── fruehsport-audio.py    # Hauptanwendung
├── Skripte/
│   ├── *.md                   # Eingabe-Skripte
│   └── *.mp3                  # Generierte Audio-Dateien
├── Anforderungen/             # Spezifikationen
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
