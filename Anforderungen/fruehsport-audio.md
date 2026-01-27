# fruehsport-audio

## Zweck

Konvertiert Frühsport-Anleitungsskripte aus dem `Skripte/`-Verzeichnis zu MP3-Audiodateien mittels OpenAI Text-to-Speech API. Die Skripte können kontrollierte Pausen enthalten, um einen Sport-Trainer zu simulieren.

## Funktionale Anforderungen

- [x] Durchsucht das `Skripte/`-Verzeichnis nach Markdown-Dateien (.md)
- [x] Prüft für jede MD-Datei, ob bereits eine gleichnamige MP3-Datei existiert
- [x] Konvertiert nur MD-Dateien, die noch keine zugehörige MP3 haben
- [x] Verwendet OpenAI TTS API für die Umwandlung
- [x] Parst `#PAUSE X` Anweisungen im Text (X = Sekunden)
- [x] Fügt Stille in der entsprechenden Länge ein
- [x] Teilt Text in Segmente auf (getrennt durch Pausen)
- [x] Fügt alle Audio-Segmente (Sprache + Stille) zu einer finalen MP3 zusammen
- [x] Zeigt Fortschritt während der Verarbeitung an

## Skript-Format

### Syntax

```markdown
Willkommen zum Frühsport!
#PAUSE 3

Erste Übung: Rückenschaukel. Drehe dich auf den Rücken.
#PAUSE 2
Und los!
#PAUSE 30

Sehr gut gemacht! Nächste Übung...
```

### Pause-Anweisung

- `#PAUSE X` wobei X die Dauer in Sekunden ist
- Die Anweisung muss auf einer eigenen Zeile stehen
- Beispiele:
  - `#PAUSE 3` - 3 Sekunden Pause (z.B. für Countdown)
  - `#PAUSE 30` - 30 Sekunden Pause (z.B. für Übungsdurchführung)
  - `#PAUSE 60` - 60 Sekunden Pause (z.B. für längere Übungen)

## Technische Anforderungen

- Python >= 3.11
- Abhängigkeiten:
  - `openai` - OpenAI Python SDK für TTS-API
  - `pydub` - Audio-Manipulation (Stille erzeugen, MP3s zusammenfügen)

## Verwendung

```bash
uv run Apps/fruehsport-audio.py
```

## Beispiele

```
$ uv run Apps/fruehsport-audio.py
Suche nach Skripten in Skripte/...
Gefunden: 2 Skript(e)
Bereits konvertiert: 0 Datei(en)
Zu konvertieren: 2 Datei(en)

[1/2] Konvertiere: fruehsport-basis.md
  - Segmente: 12 (6 Sprache, 6 Pausen)
  - Stimme: nova
  - Verarbeite Segmente...
  - MP3 erstellt: fruehsport-basis.mp3

[2/2] Konvertiere: fruehsport-intensiv.md
  - Segmente: 24 (12 Sprache, 12 Pausen)
  - Stimme: nova
  - MP3 erstellt: fruehsport-intensiv.mp3

Fertig! 2 Datei(en) konvertiert.
```

## Konfiguration

Die App verwendet folgende OpenAI TTS-Einstellungen:
- **Modell**: `gpt-4o-mini-tts` (mit Fallback auf `tts-1`)
- **Stimme**: `nova` (motivierende Stimme für Sport-Anleitung)
- **Format**: MP3
