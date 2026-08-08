# ADR-0001: Polling-Ducking mit Adapter-Abstraktion für den Podcast-Player

**Status**: Akzeptiert
**Datum**: 2026-08-08
**Entscheider**: sthof (Vorgaben), Claude (Ausarbeitung)
**Kontext-Anforderung**: R00002

## Kontext

Der Podcast-Player (`Apps/podcast-player.py`) muss laufende Spotify-Streams über die gesamte Playlist-Dauer absenken — auch Streams, die erst während der Wiedergabe entstehen (Titelwechsel, Pause/Play). Auf dem Zielsystem (PipeWire 1.2.7 mit pipewire-pulse) steht `module-role-ducking` nicht zur Verfügung. Tests dürfen weder echtes Audio noch ein laufendes Spotify voraussetzen.

## Optionen

### Option A: Server-natives Ducking (module-role-ducking / WirePlumber-Policy)
- Vorteile: kein eigener Code für Erkennung/Fade; robust auch ohne laufenden Player-Prozess.
- Nachteile: auf dem Zielsystem nicht verfügbar („No such entity", verifiziert 2026-08-08); WirePlumber-Policy erfordert Systemkonfiguration außerhalb des Repos.

### Option B: Event-basierte Überwachung (`pactl subscribe`)
- Vorteile: reagiert sofort statt in einem Poll-Intervall; keine periodische Prozess-Spawns.
- Nachteile: Dauerhaft laufender Subprozess mit Zeilenstrom, komplexeres Parsen und Lifecycle-Management; in Tests deutlich schwerer zu faken.

### Option C: Polling alle 2 s über `pactl list sink-inputs` hinter Adaptern
- Vorteile: einfacher, deterministischer Code; Adapter (`AudioMixer`, `PlayerBackend`) und austauschbare `DuckingStrategy` machen alles mit Fakes testbar; 2 s Reaktionszeit ist für den Anwendungsfall ausreichend.
- Nachteile: bis zu 2 s Verzögerung bei neuen Streams; alle 2 s ein `pactl`-Aufruf.

## Entscheidung

**Gewählt: Option C** — Polling-Ducking hinter einer austauschbaren `DuckingStrategy`-Abstraktion, `pactl` und Player-Start jeweils hinter schmalen Adaptern. Option A bleibt als späteres, server-natives Backend vorgesehen und ist dank der Abstraktion ohne Änderung am Player ergänzbar.

## Konsequenzen

- Neue Spotify-Streams werden spätestens nach 2 s erkannt und sanft abgesenkt.
- Tests ersetzen `AudioMixer` und `PlayerBackend` durch Fakes; kein echter pactl-/mpv-/mplayer-Aufruf in der Testsuite.
- Ein späteres WirePlumber-Backend implementiert nur das `DuckingStrategy`-Interface.

## Festlegungen zu offenen Fragen der Anforderung (Vorgaben des Users)

- **Logdatei**: `Logs/podcast-player.jsonl` im Projekt-Root, ein JSON-Objekt pro Zeile:
  `{"zeit": ISO-8601, "ereignis": "start"|"ende"|"abbruch"|"fehler", "datei": Pfad, "dauer_s": Zahl|null, "detail": String|null}`
- **Fade-Parameter**: wie im bewährten Wrapper `~/.claude/scripts/spotify-ducking.sh` — 10 Schritte, 0,08 s Schrittabstand.
- **Ordner-Argumente**: enthaltene `*.mp3` alphabetisch sortiert, locale-unabhängig und case-insensitive.
