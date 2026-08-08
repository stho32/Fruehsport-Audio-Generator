"""E2E-Tests fuer den Player: das CLI ``Apps/podcast-player.py`` als echter Subprozess.

Der Player kommt als Fake-Skript ueber PATH-Injektion aus ``fakes.py`` —
es laeuft kein echtes Audio; ein pactl existiert im PATH bewusst nicht
(R00003). Kein Netzwerk-Port noetig (reines CLI); die Skill-Regel
"freier Port" ist damit gegenstandslos.
"""

from __future__ import annotations

import json
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fakes import FakeUmgebung

PROJEKT_ROOT = Path(__file__).resolve().parent.parent
CLI = PROJEKT_ROOT / "Apps" / "podcast-player.py"


@pytest.fixture
def umgebung(tmp_path):
    return FakeUmgebung(tmp_path, player_namen=("fake-player", "mpv"))


def cli_befehl(umgebung, tmp_path, argumente):
    log_datei = tmp_path / "abspiel-log.jsonl"
    return (
        [sys.executable, str(CLI), *argumente, "--log-datei", str(log_datei)],
        log_datei,
    )


def starte_cli(umgebung, tmp_path, argumente, **popen_kwargs):
    befehl, log_datei = cli_befehl(umgebung, tmp_path, argumente)
    ergebnis = subprocess.run(
        befehl, env=umgebung.umgebungsvariablen(), capture_output=True,
        text=True, timeout=30, check=False, **popen_kwargs,
    )
    log = (
        [json.loads(z) for z in log_datei.read_text(encoding="utf-8").splitlines()]
        if log_datei.exists()
        else []
    )
    return ergebnis, log


def erstelle_mp3s(tmp_path, *namen):
    pfade = []
    for name in namen:
        pfad = tmp_path / name
        pfad.parent.mkdir(parents=True, exist_ok=True)
        pfad.touch()
        pfade.append(str(pfad))
    return pfade


class TestE2EPlaylist:
    def test_drei_dateien_reihenfolge_und_log(self, umgebung, tmp_path):
        dateien = erstelle_mp3s(tmp_path, "a.mp3", "b.mp3", "c.mp3")
        backend = str(umgebung.fakebin / "fake-player")

        ergebnis, log = starte_cli(
            umgebung, tmp_path, [*dateien, "--backend", backend]
        )

        assert ergebnis.returncode == 0
        abspielungen = umgebung.abgespielte_dateien()
        assert [Path(e["datei"]).name for e in abspielungen] == ["a.mp3", "b.mp3", "c.mp3"]
        # Abspiel-Log: start/ende je Datei, maschinenlesbar:
        assert [(e["ereignis"], Path(e["datei"]).name) for e in log] == [
            ("start", "a.mp3"), ("ende", "a.mp3"),
            ("start", "b.mp3"), ("ende", "b.mp3"),
            ("start", "c.mp3"), ("ende", "c.mp3"),
        ]
        assert all("zeit" in e for e in log)

    def test_ordner_argument_und_mpv_default(self, umgebung, tmp_path):
        erstelle_mp3s(tmp_path, "folge/Beta.mp3", "folge/alpha.mp3")

        ergebnis, _log = starte_cli(umgebung, tmp_path, [str(tmp_path / "folge")])

        assert ergebnis.returncode == 0
        abspielungen = umgebung.abgespielte_dateien()
        assert [Path(e["datei"]).name for e in abspielungen] == ["alpha.mp3", "Beta.mp3"]
        assert abspielungen[0]["argv"][:2] == ["--no-video", "--really-quiet"]

    def test_kaputte_datei_rest_laeuft_exit_1_und_fehler_im_log(
        self, umgebung, tmp_path
    ):
        dateien = erstelle_mp3s(tmp_path, "a.mp3", "kaputt.mp3", "c.mp3")
        backend = str(umgebung.fakebin / "fake-player")

        ergebnis, log = starte_cli(
            umgebung, tmp_path, [*dateien, "--backend", backend]
        )

        assert ergebnis.returncode == 1
        assert [Path(e["datei"]).name for e in umgebung.abgespielte_dateien()] == [
            "a.mp3", "kaputt.mp3", "c.mp3",
        ]
        ereignisse = [(e["ereignis"], Path(e["datei"]).name) for e in log]
        assert ("fehler", "kaputt.mp3") in ereignisse
        assert ("ende", "c.mp3") in ereignisse

    def test_fehlende_datei_ergibt_exit_2_und_meldung(self, umgebung, tmp_path):
        ergebnis, log = starte_cli(
            umgebung, tmp_path, [str(tmp_path / "gibtsnicht.mp3")]
        )

        assert ergebnis.returncode == 2
        assert "nicht gefunden" in ergebnis.stderr
        assert log == []
        assert umgebung.abgespielte_dateien() == []


class TestE2EKeinDucking:
    """US-1 (R00003): der Player fasst keine Lautstaerken mehr an."""

    def test_level_wird_als_unbekanntes_argument_abgewiesen(self, umgebung, tmp_path):
        dateien = erstelle_mp3s(tmp_path, "a.mp3")
        backend = str(umgebung.fakebin / "fake-player")

        ergebnis, log = starte_cli(
            umgebung, tmp_path, ["--level", "35", *dateien, "--backend", backend]
        )

        assert ergebnis.returncode == 2
        assert "--level" in ergebnis.stderr
        assert log == []
        assert umgebung.abgespielte_dateien() == []

    def test_wiedergabe_ohne_pactl_im_pfad_laeuft_fehlerfrei(self, umgebung, tmp_path):
        # PATH enthaelt nur das fakebin — und dort liegt kein pactl.
        assert not (umgebung.fakebin / "pactl").exists()
        dateien = erstelle_mp3s(tmp_path, "a.mp3")
        backend = str(umgebung.fakebin / "fake-player")

        ergebnis, log = starte_cli(
            umgebung, tmp_path, [*dateien, "--backend", backend]
        )

        assert ergebnis.returncode == 0
        assert [e["ereignis"] for e in log] == ["start", "ende"]


class TestE2ESignale:
    @pytest.mark.parametrize(
        "signalnummer,erwarteter_exit",
        [(signal.SIGINT, 130), (signal.SIGTERM, 143)],
        ids=["SIGINT", "SIGTERM"],
    )
    def test_signal_stoppt_wiedergabe_mit_abbruch_log(
        self, umgebung, tmp_path, signalnummer, erwarteter_exit
    ):
        dateien = erstelle_mp3s(tmp_path, "lang.mp3")
        backend = str(umgebung.fakebin / "fake-player")
        env = umgebung.umgebungsvariablen()
        env["FAKE_PLAYER_SLEEP"] = "30"
        befehl, log_datei = cli_befehl(
            umgebung, tmp_path, [*dateien, "--backend", backend]
        )

        prozess = subprocess.Popen(
            befehl, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        # Warten bis die Wiedergabe wirklich laeuft (Fake-Player hat geloggt):
        frist = time.monotonic() + 10
        while not umgebung.player_log.exists() and time.monotonic() < frist:
            time.sleep(0.05)
        assert umgebung.player_log.exists(), "Wiedergabe kam nie an"

        prozess.send_signal(signalnummer)
        exit_code = prozess.wait(timeout=15)

        assert exit_code == erwarteter_exit
        log = [
            json.loads(z)
            for z in log_datei.read_text(encoding="utf-8").splitlines()
        ]
        assert [(e["ereignis"], Path(e["datei"]).name) for e in log] == [
            ("start", "lang.mp3"), ("abbruch", "lang.mp3"),
        ]
        assert f"Signal {int(signalnummer)}" in log[-1]["detail"]
