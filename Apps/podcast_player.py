"""podcast_player: Podcast-Playlists als CLI abspielen.

Kernmodul zu R00002 (Player) und R00003 (Rueckbau des Ducking, siehe ADR-0002).
Der CLI-Einstieg ist ``podcast-player.py`` im selben Verzeichnis.

Architektur (Adapter-Muster, alles Externe gekapselt):

- ``PlayerBackend``   — Adapter fuer den Player-Prozess (mpv, Fallback mplayer)
- ``EventLog``        — JSONL-Abspiel-Log (``Logs/podcast-player.jsonl``)
- ``PodcastPlayer``   — Orchestrierung: Playlist, Warteschleife, Signale

Der Player beruehrt keinerlei Lautstaerken; die Absenkung anderer Quellen
(z. B. Spotify) erfolgt manuell durch den Nutzer (ADR-0002).

Es werden ausschliesslich Standardbibliotheks-Module verwendet.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import shutil
import signal
import subprocess
import sys
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

# --- Festlegungen ------------------------------------------------------------

EXIT_OK = 0
EXIT_DATEI_FEHLER = 1            # mindestens eine Datei nicht abspielbar
EXIT_BENUTZUNG = 2               # Argument-/Playlist-Fehler
EXIT_SIGINT = 130
EXIT_SIGTERM = 143


class PlaylistFehler(Exception):
    """Ein Argument ergibt keine abspielbare Playlist (fehlende Datei, leerer Ordner)."""


class PlayerNichtGefunden(Exception):
    """Weder mpv noch mplayer verfuegbar."""


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

    def __init__(self, basis_befehl: list[str], terminate_timeout_s: float = 5.0) -> None:
        self.basis_befehl = basis_befehl
        self._terminate_timeout_s = terminate_timeout_s
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
                self._prozess.wait(timeout=self._terminate_timeout_s)
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
    und case-insensitive. Nicht existierende Argumente und Ordner ohne MP3s
    sind Benutzungsfehler (``PlaylistFehler``).
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
    """Append-only JSONL-Log, ein JSON-Objekt pro Zeile.

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
    """Spielt eine Playlist ab und protokolliert jedes Ereignis."""

    playlist: list[Path]
    backend: PlayerBackend
    log: EventLog
    warte_schritt_s: float = 0.1
    sleep: Callable[[float], None] = time.sleep
    monotonic: Callable[[], float] = time.monotonic
    _abbruch_signal: int | None = field(default=None, init=False)

    def fordere_abbruch_an(self, signalnummer: int) -> None:
        """Signal-sicher: merkt den Abbruchwunsch fuer die Hauptschleife."""
        self._abbruch_signal = signalnummer

    def run(self) -> int:
        datei_fehler = False
        for datei in self.playlist:
            ergebnis = self._spiele_datei(datei)
            if ergebnis == "abbruch":
                return _exit_code_fuer_signal(self._abbruch_signal)
            if ergebnis == "fehler":
                datei_fehler = True
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

        exit_code = self._warte_bis_ende()
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

    def _warte_bis_ende(self) -> int | None:
        """Wartet auf das Player-Ende.

        Liefert den Exit-Code des Players oder None bei Signal-Abbruch.
        """
        while True:
            if self._abbruch_signal is not None:
                return None
            exit_code = self.backend.poll()
            if exit_code is not None:
                return exit_code
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
        description="Spielt MP3-Dateien als eine Playlist ab.",
    )
    parser.add_argument(
        "eingaben", nargs="+", metavar="DATEI_ODER_ORDNER",
        help="MP3-Dateien und/oder Ordner mit MP3-Dateien, in Abspielreihenfolge",
    )
    parser.add_argument(
        "--backend", default=None, metavar="BEFEHL",
        help="Player-Befehl erzwingen statt mpv/mplayer-Erkennung (v.a. fuer Tests)",
    )
    parser.add_argument(
        "--log-datei", type=Path, default=None, metavar="PFAD",
        help="Pfad der Logdatei (Default: Logs/podcast-player.jsonl im Projekt)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    argumente = parse_argumente(argv if argv is not None else sys.argv[1:])

    try:
        playlist = baue_playlist(argumente.eingaben)
        backend = finde_player_backend(override=argumente.backend)
    except (PlaylistFehler, PlayerNichtGefunden) as fehler:
        print(f"Fehler: {fehler}", file=sys.stderr)
        return EXIT_BENUTZUNG

    log = EventLog(argumente.log_datei or standard_log_pfad())
    player = PodcastPlayer(playlist=playlist, backend=backend, log=log)

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


if __name__ == "__main__":  # pragma: no cover — Einstieg laeuft nur im E2E-Subprozess
    sys.exit(main())
