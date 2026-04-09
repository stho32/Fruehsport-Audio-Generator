# CLAUDE.md

## Projektbeschreibung

Fruehsport-Audio-Generator generiert MP3-Audiodateien mit Sprache und Pausen aus Markdown-Skripten.
Die Skripte enthalten Text (wird via OpenAI TTS gesprochen), Pause-Anweisungen und optionale Audio-Includes.

## TechStack

- **Sprache**: Python (>= 3.11)
- **Paketmanager**: uv (inline script dependencies)
- **Architektur-Vorlage**: python-uv-app
- **Audio**: pydub, ffmpeg
- **TTS**: OpenAI API (Modell: gpt-4o-mini-tts, Stimme: nova)

## Projektstruktur

```
Apps/                  # Python-Anwendungen
  fruehsport-audio.py # Hauptanwendung (Single-File mit inline dependencies)
Skripte/               # Eingabe-Skripte (.md) und generierte Audio (.mp3)
Anforderungen/         # Anforderungsdokumente
```

## Run-Befehle

```bash
# Anwendung ausfuehren (konvertiert alle neuen Skripte zu MP3)
uv run Apps/fruehsport-audio.py
```

## Voraussetzungen

- [uv](https://docs.astral.sh/uv/) installiert
- [ffmpeg](https://ffmpeg.org/) installiert und im PATH
- Umgebungsvariable `OPENAI_API_KEY` gesetzt

## Konventionen

- Anforderungen liegen in `Anforderungen/` im Format `RXXXXX-name.md` mit YAML-Frontmatter
- Commits referenzieren Anforderungs-IDs: `[RXXXXX] Beschreibung`
- Single-File-Scripts mit inline uv dependencies (PEP 723)
- Skript-Direktiven: `#PAUSE X`, `#INCLUDE datei.mp3`, `#START`
