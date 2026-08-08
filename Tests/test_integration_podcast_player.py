"""Integrationstests fuer podcast_player (R00002/R00003).

Testen das Zusammenspiel der Module: ``main()`` in-process mit den
ausfuehrbaren Fake-Player-Skripten aus ``fakes.py`` — Subprozess-Plumbing
inklusive, aber ohne echtes mpv/mplayer und ohne Audio. Szenarien
entsprechen den User Stories in Anforderungen/user-stories/R00003.md.
"""

from __future__ import annotations

import json
import signal
import sys
from pathlib import Path

import podcast_player as pp
import pytest
from fakes import FakeUmgebung


@pytest.fixture
def umgebung(tmp_path, monkeypatch):
    """FakeUmgebung, deren Variablen (inkl. PATH=fakebin) aktiv sind."""
    fake = FakeUmgebung(tmp_path, player_namen=("fake-player", "mpv", "mplayer"))
    for name, wert in fake.umgebungsvariablen().items():
        monkeypatch.setenv(name, wert)
    return fake


@pytest.fixture
def mp3s(tmp_path):
    def erstelle(*namen: str) -> list[str]:
        pfade = []
        for name in namen:
            pfad = tmp_path / name
            pfad.parent.mkdir(parents=True, exist_ok=True)
            pfad.touch()
            pfade.append(str(pfad))
        return pfade
    return erstelle


def starte_main(umgebung, tmp_path, argumente):
    log_datei = tmp_path / "abspiel-log.jsonl"
    exit_code = pp.main([*argumente, "--log-datei", str(log_datei)])
    log = (
        [json.loads(z) for z in log_datei.read_text(encoding="utf-8").splitlines()]
        if log_datei.exists()
        else []
    )
    return exit_code, log


# --- US-2: Playlist abspielen -------------------------------------------------

class TestPlaylistAbspielen:
    def test_mehrere_dateien_in_aufrufreihenfolge(self, umgebung, tmp_path, mp3s):
        dateien = mp3s("a.mp3", "b.mp3", "c.mp3")
        backend = str(umgebung.fakebin / "fake-player")

        exit_code, log = starte_main(
            umgebung, tmp_path, [*dateien, "--backend", backend]
        )

        assert exit_code == 0
        assert [Path(e["datei"]).name for e in umgebung.abgespielte_dateien()] == [
            "a.mp3", "b.mp3", "c.mp3",
        ]
        assert [(e["ereignis"], Path(e["datei"]).name) for e in log] == [
            ("start", "a.mp3"), ("ende", "a.mp3"),
            ("start", "b.mp3"), ("ende", "b.mp3"),
            ("start", "c.mp3"), ("ende", "c.mp3"),
        ]

    def test_ordner_argument_spielt_enthaltene_mp3s(self, umgebung, tmp_path, mp3s):
        mp3s("ordner/zwei.mp3", "ordner/Eins.mp3")
        backend = str(umgebung.fakebin / "fake-player")

        exit_code, _log = starte_main(
            umgebung, tmp_path, [str(tmp_path / "ordner"), "--backend", backend]
        )

        assert exit_code == 0
        assert [Path(e["datei"]).name for e in umgebung.abgespielte_dateien()] == [
            "Eins.mp3", "zwei.mp3",
        ]

    def test_fehlendes_argument_ergibt_exit_2_ohne_wiedergabe(
        self, umgebung, tmp_path, capsys
    ):
        exit_code, _log = starte_main(
            umgebung, tmp_path, [str(tmp_path / "gibtsnicht.mp3")]
        )

        assert exit_code == 2
        assert "nicht gefunden" in capsys.readouterr().err
        assert umgebung.abgespielte_dateien() == []


# --- US-1: Keine Lautstaerke-Eingriffe, --level abgewiesen --------------------

class TestKeineLautstaerkeEingriffe:
    def test_level_wird_als_unbekanntes_argument_abgewiesen(
        self, umgebung, tmp_path, mp3s, capsys
    ):
        dateien = mp3s("a.mp3")

        with pytest.raises(SystemExit) as abbruch:
            starte_main(umgebung, tmp_path, ["--level", "35", *dateien])

        assert abbruch.value.code == 2
        assert "--level" in capsys.readouterr().err
        assert umgebung.abgespielte_dateien() == []

    def test_wiedergabe_startet_keinen_pactl_prozess(self, umgebung, tmp_path, mp3s):
        # PATH enthaelt nur das fakebin — ohne pactl. Ein pactl-Aufruf des
        # Players wuerde hier als OSError/Fehler sichtbar.
        assert not (umgebung.fakebin / "pactl").exists()
        dateien = mp3s("a.mp3")
        backend = str(umgebung.fakebin / "fake-player")

        exit_code, log = starte_main(
            umgebung, tmp_path, [*dateien, "--backend", backend]
        )

        assert exit_code == 0
        assert [e["ereignis"] for e in log] == ["start", "ende"]


# --- US-2.3: Backend-Wahl -----------------------------------------------------

class TestBackendWahl:
    def test_mpv_ist_default_mit_no_video_und_quiet(self, umgebung, tmp_path, mp3s):
        dateien = mp3s("a.mp3")

        exit_code, _log = starte_main(umgebung, tmp_path, dateien)

        assert exit_code == 0
        argv = umgebung.abgespielte_dateien()[0]["argv"]
        assert argv[:2] == ["--no-video", "--really-quiet"]

    def test_mplayer_fallback_wenn_mpv_fehlt(self, umgebung, tmp_path, mp3s):
        (umgebung.fakebin / "mpv").unlink()
        dateien = mp3s("a.mp3")

        exit_code, _log = starte_main(umgebung, tmp_path, dateien)

        assert exit_code == 0
        argv = umgebung.abgespielte_dateien()[0]["argv"]
        assert argv[0] == "-really-quiet"

    def test_kein_player_verfuegbar_ergibt_exit_2(
        self, umgebung, tmp_path, mp3s, capsys
    ):
        (umgebung.fakebin / "mpv").unlink()
        (umgebung.fakebin / "mplayer").unlink()
        dateien = mp3s("a.mp3")

        exit_code, _log = starte_main(umgebung, tmp_path, dateien)

        assert exit_code == 2
        assert "mpv" in capsys.readouterr().err
        assert umgebung.abgespielte_dateien() == []


# --- US-5: Fehlertoleranz in der Playlist -------------------------------------

class TestFehlertoleranz:
    def test_kaputte_datei_mittendrin_rest_laeuft_exit_ungleich_0(
        self, umgebung, tmp_path, mp3s
    ):
        dateien = mp3s("a.mp3", "kaputt.mp3", "c.mp3")
        backend = str(umgebung.fakebin / "fake-player")

        exit_code, log = starte_main(
            umgebung, tmp_path, [*dateien, "--backend", backend]
        )

        assert exit_code == 1
        assert [Path(e["datei"]).name for e in umgebung.abgespielte_dateien()] == [
            "a.mp3", "kaputt.mp3", "c.mp3",
        ]
        ereignisse = [(e["ereignis"], Path(e["datei"]).name) for e in log]
        assert ("fehler", "kaputt.mp3") in ereignisse
        assert ("ende", "c.mp3") in ereignisse


# --- CommandPlayerBackend-Lebenszyklus (harmloser Python-Kindprozess) ---------

def python_backend(*code: str, **kwargs) -> pp.CommandPlayerBackend:
    """Backend, dessen 'Player' ein kurzes Python-Programm ist (kein echter Player).

    Der Dateiname wird vom Backend als letztes Argument angehaengt und vom
    Programm ignoriert.
    """
    return pp.CommandPlayerBackend([sys.executable, "-c", *code], **kwargs)


class TestCommandPlayerBackend:
    def test_poll_vor_start_liefert_none(self):
        assert python_backend("pass").poll() is None

    def test_erfolgreiches_ende_liefert_exit_0(self):
        backend = python_backend("pass")
        backend.start(Path("egal.mp3"))

        while (exit_code := backend.poll()) is None:
            pass

        assert exit_code == 0

    def test_fehlschlag_liefert_exit_code_ungleich_0(self):
        backend = python_backend("import sys; sys.exit(3)")
        backend.start(Path("egal.mp3"))

        while (exit_code := backend.poll()) is None:
            pass

        assert exit_code == 3

    def test_terminate_beendet_laufenden_prozess(self):
        backend = python_backend("import time; time.sleep(30)")
        backend.start(Path("egal.mp3"))
        assert backend.poll() is None  # laeuft wirklich

        backend.terminate()

        assert backend.poll() is not None  # beendet, kein Zombie

    def test_terminate_ohne_laufenden_prozess_ist_harmlos(self):
        backend = python_backend("import time; time.sleep(30)")
        backend.terminate()  # nie gestartet — keine Exception

        backend.start(Path("egal.mp3"))
        backend.terminate()
        backend.terminate()  # bereits beendet — idempotent

        assert backend.poll() is not None

    def test_terminate_killt_prozess_der_sigterm_ignoriert(self):
        backend = python_backend(
            "import signal, time\n"
            "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            "time.sleep(30)",
            terminate_timeout_s=0.3,
        )
        backend.start(Path("egal.mp3"))
        import time as _time
        _time.sleep(0.3)  # Kind Zeit geben, den SIGTERM-Ignore zu installieren

        backend.terminate()

        assert backend.poll() is not None  # via SIGKILL beendet


# --- US-4: Sauberer Abbruch (Signal-Handler von main) -------------------------

class TestSignalHandlerVonMain:
    def test_sigint_waehrend_wiedergabe_bricht_ab_und_stellt_handler_wieder_her(
        self, umgebung, tmp_path, mp3s, monkeypatch
    ):
        monkeypatch.setenv("FAKE_PLAYER_SLEEP", "5")
        # Der Fake-Player schickt bei "sendesignal" SIGINT an diesen Prozess:
        dateien = mp3s("sendesignal.mp3")
        backend = str(umgebung.fakebin / "fake-player")
        handler_vorher = signal.getsignal(signal.SIGINT)

        exit_code, log = starte_main(
            umgebung, tmp_path, [*dateien, "--backend", backend]
        )

        assert exit_code == 130
        assert [e["ereignis"] for e in log] == ["start", "abbruch"]
        assert signal.getsignal(signal.SIGINT) is handler_vorher  # Handler restauriert


# --- US-3: Abspiel-Log (Standardpfad) -----------------------------------------

class TestLogStandardpfad:
    def test_standard_log_pfad_liegt_im_projekt(self):
        erwartet = Path(pp.__file__).resolve().parent.parent / "Logs" / "podcast-player.jsonl"
        assert pp.standard_log_pfad() == erwartet
