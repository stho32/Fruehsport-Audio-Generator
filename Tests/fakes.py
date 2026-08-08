"""Ausfuehrbare Fake-Skripte fuer Integrations- und E2E-Tests (R00002).

Erzeugt in einem Testverzeichnis ein ``fakebin`` mit:

- ``pactl``       — simuliert `pactl list sink-inputs` / `set-sink-input-volume`
                    ueber eine JSON-Zustandsdatei (echte Zustandsuebergaenge,
                    atomare Writes) plus Aufruf-Protokoll.
- Player-Skripte  — protokollieren jeden Abspielvorgang inkl. des Spotify-
                    Zustands zum Startzeitpunkt. Verhalten je Dateiname:
                    ``kaputt`` -> Exit 1, ``neuerstream`` -> laesst einen neuen
                    Sink-Input (#55, 90%) auftauchen. Schlafdauer via
                    ``FAKE_PLAYER_SLEEP``.

Es laeuft nie ein echter pactl-, mpv- oder mplayer-Prozess.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

FAKE_PACTL_QUELLTEXT = f'''#!{sys.executable}
import json, os, sys, tempfile

STATE = os.environ["FAKE_PACTL_STATE"]
CALLS = os.environ["FAKE_PACTL_CALLS"]


def lade():
    try:
        with open(STATE) as f:
            return json.load(f)
    except FileNotFoundError:
        return {{}}


def speichere(zustand):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(STATE))
    with os.fdopen(fd, "w") as f:
        json.dump(zustand, f)
    os.replace(tmp, STATE)


args = sys.argv[1:]
if args[:2] == ["list", "sink-inputs"]:
    for sid, vol in lade().items():
        print(f"Sink Input #{{sid}}")
        print(f"\\tVolume: front-left: 65536 / {{vol}}% / 0.00 dB,"
              f"   front-right: 65536 / {{vol}}% / 0.00 dB")
        print("\\tProperties:")
        print('\\t\\tapplication.name = "spotify"')
elif args and args[0] == "set-sink-input-volume":
    sid, vol = args[1], int(args[2].rstrip("%"))
    zustand = lade()
    if sid in zustand:
        zustand[sid] = vol
        speichere(zustand)
    with open(CALLS, "a") as f:
        f.write(f"{{sid}} {{vol}}\\n")
else:
    sys.exit(1)
'''

FAKE_PLAYER_QUELLTEXT = f'''#!{sys.executable}
import json, os, sys, tempfile, time

datei = sys.argv[-1]
name = os.path.basename(datei)
state_pfad = os.environ.get("FAKE_PACTL_STATE")


def lade_state():
    try:
        with open(state_pfad) as f:
            return json.load(f)
    except (FileNotFoundError, TypeError):
        return {{}}


with open(os.environ["FAKE_PLAYER_LOG"], "a") as f:
    f.write(json.dumps({{
        "datei": datei,
        "argv": sys.argv[1:],
        "sink_state": lade_state(),
    }}) + "\\n")

if "neuerstream" in name and state_pfad:
    zustand = lade_state()
    zustand["55"] = 90
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(state_pfad))
    with os.fdopen(fd, "w") as f:
        json.dump(zustand, f)
    os.replace(tmp, state_pfad)

time.sleep(float(os.environ.get("FAKE_PLAYER_SLEEP", "0")))
sys.exit(1 if "kaputt" in name else 0)
'''


class FakeUmgebung:
    """Legt fakebin, Zustands- und Protokolldateien an und liefert die Umgebung."""

    def __init__(self, wurzel: Path, player_namen: tuple[str, ...] = ("fake-player",)) -> None:
        self.wurzel = wurzel
        self.fakebin = wurzel / "fakebin"
        self.fakebin.mkdir()
        self.state_datei = wurzel / "pactl-state.json"
        self.calls_datei = wurzel / "pactl-calls.log"
        self.player_log = wurzel / "player.log"
        self._schreibe_skript(self.fakebin / "pactl", FAKE_PACTL_QUELLTEXT)
        for name in player_namen:
            self._schreibe_skript(self.fakebin / name, FAKE_PLAYER_QUELLTEXT)

    @staticmethod
    def _schreibe_skript(pfad: Path, quelltext: str) -> None:
        pfad.write_text(quelltext, encoding="utf-8")
        pfad.chmod(pfad.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    def setze_spotify_inputs(self, inputs: dict[int, int]) -> None:
        self.state_datei.write_text(
            json.dumps({str(k): v for k, v in inputs.items()}), encoding="utf-8"
        )

    def spotify_inputs(self) -> dict[int, int]:
        return {
            int(k): v
            for k, v in json.loads(self.state_datei.read_text(encoding="utf-8")).items()
        }

    def set_volume_aufrufe(self) -> list[tuple[int, int]]:
        if not self.calls_datei.exists():
            return []
        return [
            (int(sid), int(vol))
            for sid, vol in (
                zeile.split() for zeile in self.calls_datei.read_text().splitlines()
            )
        ]

    def abgespielte_dateien(self) -> list[dict]:
        if not self.player_log.exists():
            return []
        return [json.loads(z) for z in self.player_log.read_text(encoding="utf-8").splitlines()]

    def umgebungsvariablen(self, nur_fakebin_im_pfad: bool = True) -> dict[str, str]:
        umgebung = dict(os.environ)
        umgebung["FAKE_PACTL_STATE"] = str(self.state_datei)
        umgebung["FAKE_PACTL_CALLS"] = str(self.calls_datei)
        umgebung["FAKE_PLAYER_LOG"] = str(self.player_log)
        umgebung["PATH"] = (
            str(self.fakebin)
            if nur_fakebin_im_pfad
            else f"{self.fakebin}{os.pathsep}{umgebung['PATH']}"
        )
        return umgebung
