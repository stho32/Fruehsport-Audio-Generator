---
id: R00002
title: Podcast-Player CLI mit robustem Spotify-Ducking
type: feature
status: draft
created: 2026-08-08
---

# podcast-player-cli

## Zweck

Ein Python-CLI (`Apps/podcast-player.py`) spielt Podcast-Folgen als eine zusammenhängende Playlist ab und senkt währenddessen laufende Spotify-Streams zuverlässig ab (Ducking). Es ersetzt die bisher ad-hoc durch KI-Sessions koordinierte Wiedergabe durch deterministischen Code.

## Problem / Kontext

Heute spielt der Bash-Wrapper `~/.claude/scripts/spotify-ducking.sh` einzelne MP3s via mplayer ab. Er duckt Spotify-Sink-Inputs (PulseAudio via pactl) nur **einmal** beim Start auf 20 % und stellt sie beim Exit wieder her. Daraus ergeben sich zwei Fehlerbilder:

1. **Neuer Stream während der Wiedergabe** (Titelwechsel, Pause/Play in Spotify): Der neue Sink-Input spielt mit Originallautstärke — es wird mittendrin laut.
2. **Mehrere Folgen hintereinander** (`wrapper f1 && wrapper f2`): Zwischen den Folgen wird kurz auf laut zurückgestellt.

Zusätzlich ist die Koordination (welche Dateien, welche Reihenfolge) bislang nicht als Code fixiert.

## Systemgegebenheiten (verifiziert 2026-08-08)

- Audio: PipeWire 1.2.7 mit pipewire-pulse; `pactl` vorhanden.
- `pactl load-module module-role-ducking` schlägt fehl („No such entity") — natives Server-Ducking steht **nicht** zur Verfügung.
- Player-Backends verfügbar: `/usr/bin/mpv` und `/usr/bin/mplayer`.
- Repo nutzt uv (Python); `Apps/` enthält bereits `fruehsport-audio.py`.
- Folgen liegen unter `~/Projekte/Podcasts/<topic>/<YYYY-MM-DD-kurzbeschreibung>/<ordnername>.mp3`.

## Funktionale Anforderungen

- CLI-Aufruf: `uv run Apps/podcast-player.py <datei.mp3> [weitere.mp3 ...]` — die Argumente bilden **eine** Playlist in Aufrufreihenfolge.
- Ordner als Argument erlaubt: die darin liegenden MP3-Dateien werden abgespielt.
- Ducking gilt über die **gesamte** Playlist-Dauer: ein Absenken am Anfang, ein Wiederherstellen am Ende.
- Überwachungs-Ducking: alle 2 s werden die Spotify-Sink-Inputs geprüft; neue Streams werden sofort sanft abgesenkt und ihre Originallautstärke gemerkt.
- Duck-Level konfigurierbar per `--level` (Default 20 %).
- Player-Backend: mpv (Default), mplayer als Fallback.
- Sauberes Verhalten bei SIGINT/SIGTERM: Wiedergabe stoppt, alle Lautstärken werden wiederhergestellt.
- Ducking-Backend als austauschbare Abstraktion (Interface).
- Abspiel-Log je Datei (Beginn/Ende/Abbruch mit Zeitstempel) in eine Logdatei im Projekt.
- Exit-Code ≠ 0 bei nicht abspielbaren Dateien; die restliche Playlist läuft trotzdem weiter.

## Akzeptanzkriterien

- [ ] `uv run Apps/podcast-player.py a.mp3 b.mp3 c.mp3` spielt die drei Dateien lückenlos nacheinander als eine Playlist in Aufrufreihenfolge ab.
- [ ] Ein Ordner als Argument wird akzeptiert; die darin enthaltenen MP3-Dateien werden abgespielt.
- [ ] Beim Start werden alle vorhandenen Spotify-Sink-Inputs auf das Duck-Level abgesenkt; erst nach Ende der **letzten** Datei wird auf die gemerkten Originallautstärken zurückgestellt — zwischen den Folgen wird nicht zurückgestellt.
- [ ] Taucht während der Wiedergabe ein neuer Spotify-Sink-Input auf (z. B. Titelwechsel, Pause/Play), wird er innerhalb von max. 2 s erkannt und mit sanftem Fade auf das Duck-Level abgesenkt; seine Originallautstärke wird gemerkt und am Ende wiederhergestellt.
- [ ] Läuft Spotify nicht (keine Spotify-Sink-Inputs), spielt der Player ohne Ducking und ohne Fehler.
- [ ] `--level` setzt das Duck-Level; ohne Angabe gilt 20 %.
- [ ] Standardmäßig wird mpv verwendet; ist mpv nicht verfügbar, wird automatisch auf mplayer zurückgefallen.
- [ ] Bei SIGINT/SIGTERM stoppt die Wiedergabe und alle geduckten Streams werden auf ihre Originallautstärke zurückgestellt, bevor der Prozess endet.
- [ ] Das Ducking ist hinter einer austauschbaren Abstraktion (Interface) gekapselt; ein späteres server-natives Backend (WirePlumber/PipeWire) ist ohne Änderung am Player ergänzbar.
- [ ] Je Datei werden Beginn, Ende bzw. Abbruch mit Zeitstempel in eine Logdatei im Projekt geschrieben (append, einfach maschinenlesbar, z. B. eine Zeile pro Ereignis).
- [ ] Ist eine Datei nicht abspielbar, wird die restliche Playlist fortgesetzt und der Prozess endet mit Exit-Code ≠ 0.
- [ ] Tests setzen keine echte Audio-Ausgabe und kein laufendes Spotify voraus: pactl- und Player-Aufrufe sind gekapselt und werden in Tests durch Fakes ersetzt (Skills `test-ehrlichkeit`, `test-pyramide`).
- [ ] `~/.claude/scripts/spotify-ducking.sh` bleibt unverändert bestehen.

## Nichtziele

- Keine GUI.
- Kein Streaming, keine Podcast-Feeds (nur lokale MP3-Dateien).
- Keine Änderung an `Apps/fruehsport-audio.py`.
- Keine Ablösung von `spotify-ducking.sh` (erfolgt später separat).

## Ungeklärte Fragen

- [ ] Pfad und exaktes Format der Logdatei (z. B. `Logs/podcast-player.log` mit einer JSON-Zeile pro Ereignis)?
- [ ] Fade-Dauer und -Schrittweite beim sanften Absenken neuer Streams?
- [ ] Verhalten, wenn ein Ordner-Argument mehrere MP3s enthält: alphabetische Reihenfolge?

## Notizen

### Verworfene Alternativen

- **Server-natives Ducking** (`module-role-ducking` bzw. WirePlumber-Policy): auf dem Zielsystem nicht verfügbar („No such entity"); bleibt als späteres austauschbares Backend vorgesehen — daher die Interface-Abstraktion.
- **Erweiterung des Bash-Wrappers** `spotify-ducking.sh`: löst weder das Neuer-Stream-Problem (Polling-Schleife in Bash fragil) noch die Playlist-Koordination; außerdem soll die Koordination als Python-Code im Repo fixiert werden.
- **Event-basierte Überwachung** (`pactl subscribe`): eleganter als Polling, aber komplexer zu parsen und in Tests schwerer zu faken; 2-s-Polling ist für den Anwendungsfall ausreichend reaktionsschnell.

### Sonstiges

- User Stories: [user-stories/R00002.md](user-stories/R00002.md)
