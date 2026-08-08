---
id: R00003
title: Ducking aus dem Podcast-Player entfernen — der Player spielt nur noch ab
type: refactoring
status: draft
created: 2026-08-08
---

# ducking-aus-player-entfernen

## Zweck

Das mit R00002 eingebaute Spotify-Ducking wird vollständig aus `Apps/podcast-player.py` entfernt. Der Player wird auf seine Kernaufgabe reduziert: lokale MP3-Dateien als eine Playlist abspielen. Die Lautstärke-Absenkung von Spotify übernimmt der Nutzer künftig manuell (z. B. weiterhin per `~/.claude/scripts/spotify-ducking.sh` oder von Hand).

## Problem / Kontext

R00002 lieferte den Player mit integriertem Polling-Ducking (Überwachung der Spotify-Sink-Inputs alle 2 s, siehe ADR-0001). Ein Live-Test zeigte jedoch: Spotify setzt bei Titelwechseln die Lautstärke bereits gemerkter Streams zurück — zuverlässiges Ducking erfordert deutlich mehr Komplexität (Re-Duck-Erkennung pro bestehendem Stream, Unterscheidung Nutzer- vs. Spotify-Änderung), als der Player tragen soll.

**Nutzerentscheidung vom 2026-08-08**: Das Ducking wird komplett aus dem Player entfernt; die Absenkung erfolgt manuell.

## Funktionale Anforderungen

- Der Player berührt keinerlei Lautstärken mehr; sämtlicher Ducking-Code entfällt (AudioMixer, DuckingStrategy, pactl-Aufrufe, `--level`).
- Alle übrigen Fähigkeiten aus R00002 bleiben unverändert erhalten (Playlist, Backend-Fallback, Log, Signal-Handling, Fehlertoleranz).
- Tests, ADR-Bestand und README werden an den reduzierten Funktionsumfang angepasst.

## Akzeptanzkriterien

- [ ] Der Player berührt keinerlei Lautstärken mehr: `Apps/podcast-player.py` und `Apps/podcast_player.py` enthalten keine pactl-Aufrufe, keinen `AudioMixer`, keine `DuckingStrategy` und kein `--level`-Argument mehr; `--level` wird als unbekanntes Argument abgewiesen.
- [ ] Playlist-Funktion bleibt erhalten: Dateien und Ordner als Argumente, Ordner-Inhalte in alphabetischer Sortierung, Wiedergabe als eine zusammenhängende Playlist in Aufrufreihenfolge.
- [ ] Player-Backend bleibt erhalten: mpv als Default, automatischer Fallback auf mplayer.
- [ ] Abspiel-Log bleibt erhalten: `Logs/podcast-player.jsonl` mit unverändertem Schema (eine JSON-Zeile je Ereignis, append).
- [ ] Signal-Handling bleibt erhalten: SIGINT/SIGTERM beendet die Wiedergabe, loggt „abbruch" und der Prozess endet mit Exit-Code 130 (SIGINT) bzw. 143 (SIGTERM).
- [ ] Fehlertoleranz bleibt erhalten: Bei einer nicht abspielbaren Datei wird die restliche Playlist fortgesetzt und der Prozess endet mit Exit-Code ≠ 0.
- [ ] Tests sind bereinigt: Alle Ducking-Tests (inkl. Fakes für pactl/AudioMixer) sind entfernt; alle verbleibenden Test-Ebenen (Unit, Integration, E2E) sind grün; das Coverage-Ziel von ~90 % über alle Ebenen bleibt erfüllt.
- [ ] ADR-0001 wird nicht gelöscht, sondern durch ein neues ADR als überholt (superseded) markiert; das neue ADR hält Entscheidung und Begründung fest (Spotify setzt Lautstärken bei Titelwechseln zurück, Komplexität übersteigt den Nutzen, manuelle Absenkung durch den Nutzer).
- [ ] Der README-Abschnitt zum Player ist angepasst: kein Ducking-Versprechen mehr, `--level` nicht mehr dokumentiert.
- [ ] `~/.claude/scripts/spotify-ducking.sh` bleibt unverändert bestehen (manuelles Werkzeug des Nutzers).

## Nichtziele

- Keine neuen Features im Player.
- Keine Änderung an `Apps/fruehsport-audio.py`.
- Keine Änderung an `~/.claude/scripts/spotify-ducking.sh`.
- Kein Ersatz-Ducking an anderer Stelle (weder WirePlumber-Policy noch separates Tool) — bewusste Nutzerentscheidung für manuelles Vorgehen.

## Ungeklärte Fragen

- [ ] Keine.

## Notizen

### Verworfene Alternativen

- **Ducking robuster machen** (Re-Duck-Erkennung, wenn Spotify gemerkte Streams zurücksetzt): erfordert Unterscheidung zwischen Spotify-internen und nutzergewollten Lautstärke-Änderungen — deutlich mehr Komplexität, als der Player tragen soll.
- **Ducking als optionales Flag behalten** (`--duck`): hält den fehleranfälligen Code und seine Testlast im Repo, obwohl der Nutzer ihn nicht mehr verwenden will.
- **Ducking in separates Tool auslagern**: Nutzerentscheidung ist manuelle Absenkung; ein weiteres Tool widerspräche dem Ziel der Vereinfachung.

### Sonstiges

- Vorgänger: [R00002](R00002-podcast-player-cli.md); dortige Ducking-Akzeptanzkriterien sind durch diese Anforderung überholt.
- Überholtes ADR: `Dokumentation/ADRs/0001-polling-ducking-mit-adapter-abstraktion.md`
- User Stories: [user-stories/R00003.md](user-stories/R00003.md)
