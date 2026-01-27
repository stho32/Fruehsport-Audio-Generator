# Fruehsport-Audio

Dieses Repository enthält UV-basierte Python-Anwendungen als Single-File-Scripts zur Erstellung von Audio-Anleitungen für Frühsport.

## Struktur

- **Anforderungen/** - Anforderungsdokumente für neue Apps (Markdown-Dateien)
- **Apps/** - Fertige UV-Single-File-Scripts
- **Skripte/** - Frühsport-Anleitungsskripte im Markdown-Format

## Verwendung

### App ausführen

```bash
uv run Apps/fruehsport-audio.py
```

### Neue App erstellen

1. Anforderungsdokument in `Anforderungen/` anlegen
2. App in `Apps/` implementieren

## Apps

| App | Beschreibung |
|-----|--------------|
| [fruehsport-audio.py](Apps/fruehsport-audio.py) | Konvertiert Frühsport-Skripte zu MP3-Audiodateien mit Pausen und Countdowns |

## Beispiel

Ein fertiges Beispiel zum Anhören:

| Skript | Audio | Beschreibung |
|--------|-------|--------------|
| [fruehsport-basis-5min.md](Skripte/fruehsport-basis-5min.md) | [fruehsport-basis-5min.mp3](Skripte/fruehsport-basis-5min.mp3) | 5-Minuten Basis-Mobilisation für den Rücken |

## Skript-Format

Die Frühsport-Skripte unterstützen folgende Syntax:

```markdown
# Mein Frühsport

Willkommen zum Frühsport!

#PAUSE 3

Erste Übung: Rückenschaukel
#PAUSE 2
Und los!
#PAUSE 30

Sehr gut! Nächste Übung...
```

### Pause-Syntax

- `#PAUSE X` - Fügt eine Pause von X Sekunden ein
- Beispiel: `#PAUSE 30` fügt 30 Sekunden Stille ein

## UV Single-File Script Format

Jede App ist ein einzelnes Python-Script mit eingebetteten Abhängigkeiten:

```python
#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "package1",
#     "package2>=1.0",
# ]
# ///

"""
App-Beschreibung hier.
"""

# Code hier...
```
