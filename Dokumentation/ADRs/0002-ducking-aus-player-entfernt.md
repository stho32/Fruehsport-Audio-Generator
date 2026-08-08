# ADR-0002: Ducking aus dem Podcast-Player entfernt — manuelle Absenkung durch den Nutzer

**Status**: Akzeptiert (ersetzt [ADR-0001](0001-polling-ducking-mit-adapter-abstraktion.md))
**Datum**: 2026-08-08
**Entscheider**: sthof (Entscheidung), Claude (Ausarbeitung)
**Kontext-Anforderung**: R00003

## Kontext

ADR-0001 legte für R00002 ein Polling-Ducking fest: der Player überwacht Spotify-Sink-Inputs alle 2 s via `pactl` und senkt sie sanft ab. Ein Live-Test am 2026-08-08 zeigte eine grundsätzliche Schwäche: **Spotify setzt bei Titelwechseln die Lautstärke bereits gemerkter Streams zurück.** Zuverlässiges Ducking bräuchte Re-Duck-Erkennung pro bestehendem Stream und die Unterscheidung zwischen Spotify-internen und nutzergewollten Lautstärke-Änderungen — deutlich mehr Komplexität, als der Player tragen soll.

## Optionen

### Option A: Ducking robuster machen (Re-Duck-Erkennung)
- Vorteile: automatisches Ducking bliebe erhalten.
- Nachteile: Heuristik zur Unterscheidung Nutzer- vs. Spotify-Änderung ist fehleranfällig; Komplexität und Testlast übersteigen den Nutzen.

### Option B: Ducking als optionales Flag behalten (`--duck`)
- Vorteile: kein Funktionsverlust für Nutzer, die es doch wollen.
- Nachteile: der fehleranfällige Code und seine Testlast blieben im Repo, obwohl der Nutzer ihn nicht mehr verwenden will.

### Option C: Ducking vollständig entfernen, Absenkung manuell
- Vorteile: Player reduziert auf seine Kernaufgabe (Playlist abspielen); keine pactl-Abhängigkeit, weniger Code und Tests; das bewährte manuelle Werkzeug `~/.claude/scripts/spotify-ducking.sh` bleibt verfügbar.
- Nachteile: keine automatische Absenkung mehr — bewusst in Kauf genommen.

## Entscheidung

**Gewählt: Option C** (Nutzerentscheidung vom 2026-08-08) — sämtliche Lautstärke-Logik (`AudioMixer`, `DuckingStrategy`, pactl-Aufrufe, Polling-Schleife, `--level`) wird entfernt. Die Absenkung anderer Quellen erfolgt manuell durch den Nutzer, z. B. per `~/.claude/scripts/spotify-ducking.sh`.

## Konsequenzen

- `Apps/podcast_player.py` enthält keinerlei pactl-/Lautstärke-Code mehr; `--level` wird als unbekanntes Argument abgewiesen.
- Alle übrigen Fähigkeiten aus R00002 (Playlist, mpv/mplayer-Fallback, JSONL-Log, Signal-Handling, Fehlertoleranz) bleiben unverändert; ihre Tests bestehen fort.
- ADR-0001 bleibt als historische Entscheidung bestehen und ist als überholt markiert.
- Ein Regressionsschutz-Test stellt sicher, dass kein Ducking-Rest (pactl, AudioMixer, DuckingStrategy, `--level`) in den Player zurückkehrt.
