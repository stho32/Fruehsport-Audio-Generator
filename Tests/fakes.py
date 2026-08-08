"""Ausfuehrbare Fake-Player-Skripte fuer Integrations- und E2E-Tests.

Erzeugt in einem Testverzeichnis ein ``fakebin`` mit Player-Skripten, die
jeden Abspielvorgang protokollieren. Verhalten je Dateiname:
``kaputt`` -> Exit 1, ``sendesignal`` -> SIGINT an den Elternprozess.
Schlafdauer via ``FAKE_PLAYER_SLEEP``.

Es laeuft nie ein echter mpv- oder mplayer-Prozess; ein ``pactl`` existiert
im ``fakebin`` bewusst nicht — jeder pactl-Aufruf des Players wuerde bei
``PATH=fakebin`` sofort scheitern (R00003: der Player beruehrt keine
Lautstaerken mehr).
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

FAKE_PLAYER_QUELLTEXT = f'''#!{sys.executable}
import json, os, signal, sys, time

datei = sys.argv[-1]
name = os.path.basename(datei)

with open(os.environ["FAKE_PLAYER_LOG"], "a") as f:
    f.write(json.dumps({{
        "datei": datei,
        "argv": sys.argv[1:],
    }}) + "\\n")

if "sendesignal" in name:
    os.kill(os.getppid(), signal.SIGINT)

time.sleep(float(os.environ.get("FAKE_PLAYER_SLEEP", "0")))
sys.exit(1 if "kaputt" in name else 0)
'''


class FakeUmgebung:
    """Legt fakebin und Protokolldatei an und liefert die Umgebungsvariablen."""

    def __init__(self, wurzel: Path, player_namen: tuple[str, ...] = ("fake-player",)) -> None:
        self.wurzel = wurzel
        self.fakebin = wurzel / "fakebin"
        self.fakebin.mkdir()
        self.player_log = wurzel / "player.log"
        for name in player_namen:
            self._schreibe_skript(self.fakebin / name, FAKE_PLAYER_QUELLTEXT)

    @staticmethod
    def _schreibe_skript(pfad: Path, quelltext: str) -> None:
        pfad.write_text(quelltext, encoding="utf-8")
        pfad.chmod(pfad.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    def abgespielte_dateien(self) -> list[dict]:
        if not self.player_log.exists():
            return []
        return [json.loads(z) for z in self.player_log.read_text(encoding="utf-8").splitlines()]

    def umgebungsvariablen(self, nur_fakebin_im_pfad: bool = True) -> dict[str, str]:
        umgebung = dict(os.environ)
        umgebung["FAKE_PLAYER_LOG"] = str(self.player_log)
        umgebung["PATH"] = (
            str(self.fakebin)
            if nur_fakebin_im_pfad
            else f"{self.fakebin}{os.pathsep}{umgebung['PATH']}"
        )
        return umgebung
