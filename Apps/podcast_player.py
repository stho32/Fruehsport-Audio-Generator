"""podcast_player: Podcast-Playlists abspielen mit robustem Spotify-Ducking.

Kernmodul zu Anforderung R00002 (siehe ../Anforderungen/R00002-podcast-player-cli.md
und ADR-0001). Der CLI-Einstieg ist ``podcast-player.py`` im selben Verzeichnis.

Architektur (Adapter-Muster, alles Externe gekapselt):

- ``AudioMixer``      — Adapter fuer pactl (Sink-Inputs lesen, Lautstaerke setzen)
- ``PlayerBackend``   — Adapter fuer den Player-Prozess (mpv, Fallback mplayer)
- ``DuckingStrategy`` — austauschbares Interface fuer das Ducking; aktuelle
  Implementierung: Polling + sanfter Fade (ADR-0001). Ein spaeteres
  server-natives Backend (WirePlumber/PipeWire) implementiert nur dieses
  Interface, der Player bleibt unveraendert.
- ``EventLog``        — JSONL-Abspiel-Log (``Logs/podcast-player.jsonl``)
- ``PodcastPlayer``   — Orchestrierung: Playlist, Ueberwachungsschleife, Signale

Es werden ausschliesslich Standardbibliotheks-Module verwendet.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import shutil
import signal
import subprocess
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

# --- Festlegungen (ADR-0001) -------------------------------------------------

DUCK_LEVEL_DEFAULT = 20          # Prozent
POLL_INTERVAL_DEFAULT_S = 2.0    # Ueberwachungsintervall
FADE_STEPS_DEFAULT = 10          # wie spotify-ducking.sh
FADE_DELAY_DEFAULT_S = 0.08      # wie spotify-ducking.sh
SPOTIFY_APP_NAME = "spotify"     # application.name, case-insensitive

EXIT_OK = 0
EXIT_DATEI_FEHLER = 1            # mindestens eine Datei nicht abspielbar
EXIT_BENUTZUNG = 2               # Argument-/Playlist-Fehler
EXIT_SIGINT = 130
EXIT_SIGTERM = 143


class PlaylistFehler(Exception):
    """Ein Argument ergibt keine abspielbare Playlist (fehlende Datei, leerer Ordner)."""


class PlayerNichtGefunden(Exception):
    """Weder mpv noch mplayer verfuegbar."""


# --- AudioMixer: pactl-Adapter ----------------------------------------------

class AudioMixer(ABC):
    """Schmaler Adapter auf den Audio-Server (pactl)."""

    @abstractmethod
    def list_spotify_inputs(self) -> dict[int, int]:
        """Spotify-Sink-Inputs als Abbildung id -> Lautstaerke in Prozent."""

    @abstractmethod
    def set_volume(self, sink_input_id: int, prozent: int) -> None:
        """Lautstaerke eines Sink-Inputs setzen."""


class PactlAudioMixer(AudioMixer):
    """AudioMixer-Implementierung ueber das pactl-Kommandozeilenwerkzeug."""

    def __init__(self, pactl_befehl: str = "pactl") -> None:
        self._pactl = pactl_befehl

    def list_spotify_inputs(self) -> dict[int, int]:
        ergebnis = subprocess.run(
            [self._pactl, "list", "sink-inputs"],
            capture_output=True, text=True,
        )
        if ergebnis.returncode != 0:
            return {}
        return parse_spotify_sink_inputs(ergebnis.stdout)

    def set_volume(self, sink_input_id: int, prozent: int) -> None:
        subprocess.run(
            [self._pactl, "set-sink-input-volume", str(sink_input_id), f"{prozent}%"],
            capture_output=True, text=True,
        )


_SINK_INPUT_RE = re.compile(r"^Sink Input #(\d+)", re.MULTILINE)
_VOLUME_RE = re.compile(r"^\s*Volume:.*?(\d+)%", re.MULTILINE)
_APP_NAME_RE = re.compile(r'application\.name = "([^"]*)"')


def parse_spotify_sink_inputs(pactl_ausgabe: str) -> dict[int, int]:
    """Parst `pactl list sink-inputs` und liefert Spotify-Inputs als id -> Volumen%.

    Erkennung ueber application.name == "spotify" (case-insensitive).
    """
    inputs: dict[int, int] = {}
    bloecke = _SINK_INPUT_RE.split(pactl_ausgabe)
    # split liefert [prefix, id1, block1, id2, block2, ...]
    for i in range(1, len(bloecke), 2):
        sink_id = int(bloecke[i])
        block = bloecke[i + 1]
        app_name = _APP_NAME_RE.search(block)
        if app_name is None or app_name.group(1).lower() != SPOTIFY_APP_NAME:
            continue
        volume = _VOLUME_RE.search(block)
        if volume is None:
            continue
        inputs[sink_id] = int(volume.group(1))
    return inputs


# --- DuckingStrategy: austauschbares Interface -------------------------------

class DuckingStrategy(ABC):
    """Austauschbares Ducking-Interface (ADR-0001).

    Lebenszyklus: ``start()`` einmal vor der Playlist, ``poll()`` periodisch
    waehrend der Wiedergabe, ``stop()`` genau einmal nach der letzten Datei
    bzw. beim Abbruch.
    """

    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def poll(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...


class FadeDuckingStrategy(DuckingStrategy):
    """Polling-Ducking mit sanftem Fade ueber einen AudioMixer.

    Merkt sich die Originallautstaerke jedes geduckten Sink-Inputs und stellt
    sie in ``stop()`` wieder her. Neue Inputs (Titelwechsel, Pause/Play) werden
    bei ``poll()`` erkannt und sofort abgesenkt; verschwundene Inputs werden
    aus der Merkliste entfernt.
    """

    def __init__(
        self,
        mixer: AudioMixer,
        duck_level: int = DUCK_LEVEL_DEFAULT,
        fade_steps: int = FADE_STEPS_DEFAULT,
        fade_delay_s: float = FADE_DELAY_DEFAULT_S,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._mixer = mixer
        self._duck_level = duck_level
        self._fade_steps = fade_steps
        self._fade_delay_s = fade_delay_s
        self._sleep = sleep
        self._originale: dict[int, int] = {}

    @property
    def gemerkte_originale(self) -> dict[int, int]:
        """Kopie der Merkliste (fuer Tests und Diagnose)."""
        return dict(self._originale)

    def start(self) -> None:
        self._duck_neue(self._mixer.list_spotify_inputs())

    def poll(self) -> None:
        aktuelle = self._mixer.list_spotify_inputs()
        # Verschwundene Inputs vergessen — ihre IDs koennen neu vergeben werden.
        for sink_id in list(self._originale):
            if sink_id not in aktuelle:
                del self._originale[sink_id]
        self._duck_neue(aktuelle)

    def stop(self) -> None:
        aktuelle = self._mixer.list_spotify_inputs()
        for sink_id, original in self._originale.items():
            if sink_id in aktuelle:
                self._fade(sink_id, self._duck_level, original)
        self._originale.clear()

    def _duck_neue(self, aktuelle: dict[int, int]) -> None:
        for sink_id, volumen in aktuelle.items():
            if sink_id in self._originale:
                continue
            self._originale[sink_id] = volumen
            self._fade(sink_id, volumen, self._duck_level)

    def _fade(self, sink_id: int, von: int, nach: int) -> None:
        for schritt in range(1, self._fade_steps + 1):
            zwischenwert = von + (nach - von) * schritt // self._fade_steps
            self._mixer.set_volume(sink_id, zwischenwert)
            if schritt < self._fade_steps:
                self._sleep(self._fade_delay_s)


# --- PlayerBackend: mpv/mplayer-Adapter --------------------------------------

class PlayerBackend(ABC):
    """Schmaler Adapter auf den Player-Kindprozess."""

    @abstractmethod
    def start(self, datei: Path) -> None:
        """Wiedergabe einer Datei starten (nicht blockierend)."""

    @abstractmethod
    def poll(self) -> int | None:
        """Exit-Code des Players oder None solange er laeuft."""

    @abstractmethod
    def terminate(self) -> None:
        """Laufenden Player beenden (idempotent)."""


class CommandPlayerBackend(PlayerBackend):
    """PlayerBackend, das einen externen Befehl (mpv/mplayer) als Subprozess startet."""

    def __init__(self, basis_befehl: list[str]) -> None:
        self.basis_befehl = basis_befehl
        self._prozess: subprocess.Popen | None = None

    def start(self, datei: Path) -> None:
        self._prozess = subprocess.Popen(
            [*self.basis_befehl, str(datei)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    def poll(self) -> int | None:
        if self._prozess is None:
            return None
        return self._prozess.poll()

    def terminate(self) -> None:
        if self._prozess is not None and self._prozess.poll() is None:
            self._prozess.terminate()
            try:
                self._prozess.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._prozess.kill()
                self._prozess.wait()


def finde_player_backend(
    which: Callable[[str], str | None] = shutil.which,
    override: str | None = None,
) -> CommandPlayerBackend:
    """mpv als Default, mplayer als Fallback; ``override`` erzwingt einen Befehl.

    Der ``override`` (CLI-Option ``--backend``) dient Tests und Sonderfaellen:
    der angegebene Befehl wird unveraendert mit der Datei als letztem Argument
    aufgerufen.
    """
    if override:
        return CommandPlayerBackend([override])
    mpv = which("mpv")
    if mpv:
        return CommandPlayerBackend([mpv, "--no-video", "--really-quiet"])
    mplayer = which("mplayer")
    if mplayer:
        return CommandPlayerBackend([mplayer, "-really-quiet"])
    raise PlayerNichtGefunden("Weder mpv noch mplayer gefunden.")


# --- Playlist ----------------------------------------------------------------

def baue_playlist(argumente: list[str]) -> list[Path]:
    """Argumente (Dateien und Ordner) zu einer Playlist in Aufrufreihenfolge.

    Ordner steuern ihre ``*.mp3`` alphabetisch sortiert bei — locale-unabhaengig
    und case-insensitive (ADR-0001). Nicht existierende Argumente und Ordner
    ohne MP3s sind Benutzungsfehler (``PlaylistFehler``).
    """
    playlist: list[Path] = []
    for argument in argumente:
        pfad = Path(argument)
        if pfad.is_dir():
            mp3s = sorted(
                (p for p in pfad.iterdir() if p.is_file() and p.suffix.lower() == ".mp3"),
                key=lambda p: p.name.casefold(),
            )
            if not mp3s:
                raise PlaylistFehler(f"Ordner enthaelt keine MP3-Dateien: {pfad}")
            playlist.extend(mp3s)
        elif pfad.is_file():
            playlist.append(pfad)
        else:
            raise PlaylistFehler(f"Datei oder Ordner nicht gefunden: {pfad}")
    return playlist


# --- EventLog: JSONL-Abspiel-Log ---------------------------------------------

class EventLog:
    """Append-only JSONL-Log, ein JSON-Objekt pro Zeile (ADR-0001).

    Format: {"zeit": ISO-8601, "ereignis": "start"|"ende"|"abbruch"|"fehler",
             "datei": Pfad, "dauer_s": Zahl|null, "detail": String|null}
    """

    def __init__(
        self,
        pfad: Path,
        uhr: Callable[[], _dt.datetime] = lambda: _dt.datetime.now().astimezone(),
    ) -> None:
        self.pfad = pfad
        self._uhr = uhr

    def schreibe(
        self,
        ereignis: str,
        datei: Path | str,
        dauer_s: float | None = None,
        detail: str | None = None,
    ) -> None:
        eintrag = {
            "zeit": self._uhr().isoformat(),
            "ereignis": ereignis,
            "datei": str(datei),
            "dauer_s": round(dauer_s, 3) if dauer_s is not None else None,
            "detail": detail,
        }
        self.pfad.parent.mkdir(parents=True, exist_ok=True)
        with self.pfad.open("a", encoding="utf-8") as log_datei:
            log_datei.write(json.dumps(eintrag, ensure_ascii=False) + "\n")


# --- Orchestrierung ----------------------------------------------------------

@dataclass
class PodcastPlayer:
    """Spielt eine Playlist ab und haelt das Ducking ueber die gesamte Dauer aktiv."""

    playlist: list[Path]
    backend: PlayerBackend
    ducking: DuckingStrategy
    log: EventLog
    poll_interval_s: float = POLL_INTERVAL_DEFAULT_S
    warte_schritt_s: float = 0.1
    sleep: Callable[[float], None] = time.sleep
    monotonic: Callable[[], float] = time.monotonic
    _abbruch_signal: int | None = field(default=None, init=False)

    def fordere_abbruch_an(self, signalnummer: int) -> None:
        """Signal-sicher: merkt den Abbruchwunsch fuer die Hauptschleife."""
        self._abbruch_signal = signalnummer

    def run(self) -> int:
        self.ducking.start()
        datei_fehler = False
        try:
            for datei in self.playlist:
                ergebnis = self._spiele_datei(datei)
                if ergebnis == "abbruch":
                    return _exit_code_fuer_signal(self._abbruch_signal)
                if ergebnis == "fehler":
                    datei_fehler = True
        finally:
            self.ducking.stop()
        return EXIT_DATEI_FEHLER if datei_fehler else EXIT_OK

    def _spiele_datei(self, datei: Path) -> str:
        """Spielt eine Datei ab; Rueckgabe: "ende" | "fehler" | "abbruch"."""
        self.log.schreibe("start", datei)
        beginn = self.monotonic()
        try:
            self.backend.start(datei)
        except OSError as fehler:
            self.log.schreibe("fehler", datei, dauer_s=0.0, detail=str(fehler))
            return "fehler"

        exit_code = self._ueberwache_bis_ende()
        dauer = self.monotonic() - beginn

        if exit_code is None:  # Abbruch durch Signal
            self.backend.terminate()
            self.log.schreibe(
                "abbruch", datei, dauer_s=dauer,
                detail=f"Signal {self._abbruch_signal}",
            )
            return "abbruch"
        if exit_code != 0:
            self.log.schreibe(
                "fehler", datei, dauer_s=dauer,
                detail=f"Player-Exit-Code {exit_code}",
            )
            return "fehler"
        self.log.schreibe("ende", datei, dauer_s=dauer)
        return "ende"

    def _ueberwache_bis_ende(self) -> int | None:
        """Wartet auf das Player-Ende; pollt dabei das Ducking.

        Liefert den Exit-Code des Players oder None bei Signal-Abbruch.
        """
        naechster_poll = self.monotonic() + self.poll_interval_s
        while True:
            if self._abbruch_signal is not None:
                return None
            exit_code = self.backend.poll()
            if exit_code is not None:
                return exit_code
            if self.monotonic() >= naechster_poll:
                self.ducking.poll()
                naechster_poll = self.monotonic() + self.poll_interval_s
            self.sleep(self.warte_schritt_s)


def _exit_code_fuer_signal(signalnummer: int | None) -> int:
    if signalnummer == signal.SIGTERM:
        return EXIT_SIGTERM
    return EXIT_SIGINT


# --- CLI ---------------------------------------------------------------------

def projekt_root() -> Path:
    return Path(__file__).resolve().parent.parent


def standard_log_pfad() -> Path:
    return projekt_root() / "Logs" / "podcast-player.jsonl"


def parse_argumente(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="podcast-player.py",
        description=(
            "Spielt MP3-Dateien als eine Playlist ab und senkt laufende "
            "Spotify-Streams fuer die gesamte Dauer ab (Ducking)."
        ),
    )
    parser.add_argument(
        "eingaben", nargs="+", metavar="DATEI_ODER_ORDNER",
        help="MP3-Dateien und/oder Ordner mit MP3-Dateien, in Abspielreihenfolge",
    )
    parser.add_argument(
        "--level", type=int, default=DUCK_LEVEL_DEFAULT, metavar="PROZENT",
        help=f"Duck-Level in Prozent (Default: {DUCK_LEVEL_DEFAULT})",
    )
    parser.add_argument(
        "--backend", default=None, metavar="BEFEHL",
        help="Player-Befehl erzwingen statt mpv/mplayer-Erkennung (v.a. fuer Tests)",
    )
    parser.add_argument(
        "--log-datei", type=Path, default=None, metavar="PFAD",
        help="Pfad der Logdatei (Default: Logs/podcast-player.jsonl im Projekt)",
    )
    parser.add_argument(
        "--poll-intervall", type=float, default=POLL_INTERVAL_DEFAULT_S,
        metavar="SEKUNDEN",
        help=f"Ueberwachungsintervall in Sekunden (Default: {POLL_INTERVAL_DEFAULT_S}; fuer Tests)",
    )
    parser.add_argument(
        "--fade-delay", type=float, default=FADE_DELAY_DEFAULT_S, metavar="SEKUNDEN",
        help=f"Pause zwischen Fade-Schritten (Default: {FADE_DELAY_DEFAULT_S}; fuer Tests)",
    )
    argumente = parser.parse_args(argv)
    if not 0 <= argumente.level <= 100:
        parser.error("--level muss zwischen 0 und 100 liegen")
    return argumente


def main(argv: list[str] | None = None) -> int:
    argumente = parse_argumente(argv if argv is not None else sys.argv[1:])

    try:
        playlist = baue_playlist(argumente.eingaben)
        backend = finde_player_backend(override=argumente.backend)
    except (PlaylistFehler, PlayerNichtGefunden) as fehler:
        print(f"Fehler: {fehler}", file=sys.stderr)
        return EXIT_BENUTZUNG

    ducking = FadeDuckingStrategy(
        mixer=PactlAudioMixer(),
        duck_level=argumente.level,
        fade_delay_s=argumente.fade_delay,
    )
    log = EventLog(argumente.log_datei or standard_log_pfad())
    player = PodcastPlayer(
        playlist=playlist,
        backend=backend,
        ducking=ducking,
        log=log,
        poll_interval_s=argumente.poll_intervall,
    )

    def signal_handler(signalnummer: int, _frame: object) -> None:
        player.fordere_abbruch_an(signalnummer)

    vorherige_handler = {
        signal.SIGINT: signal.signal(signal.SIGINT, signal_handler),
        signal.SIGTERM: signal.signal(signal.SIGTERM, signal_handler),
    }
    try:
        return player.run()
    finally:
        for signalnummer, handler in vorherige_handler.items():
            signal.signal(signalnummer, handler)


if __name__ == "__main__":
    sys.exit(main())
