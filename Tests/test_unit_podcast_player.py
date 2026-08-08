"""Unit-Tests fuer podcast_player (R00002/R00003) — reine Logik, keine Subprozesse."""

from __future__ import annotations

import datetime as dt
import inspect
import json
import signal
from pathlib import Path

import podcast_player as pp
import pytest
from conftest import FakePlayerBackend, FakeUhr

# --- R00003: keine Lautstaerke-Logik mehr im Modul ----------------------------

class TestKeineLautstaerkeLogik:
    """Regressionsschutz fuer den Rueckbau (R00003, ADR-0002)."""

    def test_modul_quelltext_enthaelt_kein_pactl_und_kein_ducking(self):
        quelltext = inspect.getsource(pp)
        for verboten in ("pactl", "AudioMixer", "DuckingStrategy", "--level"):
            assert verboten not in quelltext, f"Ducking-Rest gefunden: {verboten}"

    def test_cli_wrapper_enthaelt_kein_pactl_und_kein_ducking(self):
        wrapper = Path(pp.__file__).resolve().parent / "podcast-player.py"
        quelltext = wrapper.read_text(encoding="utf-8")
        for verboten in ("pactl", "AudioMixer", "DuckingStrategy", "--level"):
            assert verboten not in quelltext, f"Ducking-Rest gefunden: {verboten}"


# --- baue_playlist ------------------------------------------------------------

class TestBauePlaylist:
    def test_dateien_in_aufrufreihenfolge(self, tmp_path):
        dateien = [tmp_path / name for name in ("b.mp3", "a.mp3", "c.mp3")]
        for datei in dateien:
            datei.touch()

        playlist = pp.baue_playlist([str(d) for d in dateien])

        assert playlist == dateien  # Aufrufreihenfolge, NICHT alphabetisch

    def test_ordner_liefert_mp3s_alphabetisch_case_insensitive(self, tmp_path):
        for name in ("Zebra.mp3", "anton.mp3", "Beta.MP3", "notiz.txt"):
            (tmp_path / name).touch()

        playlist = pp.baue_playlist([str(tmp_path)])

        assert [p.name for p in playlist] == ["anton.mp3", "Beta.MP3", "Zebra.mp3"]

    def test_gemischte_argumente_behalten_reihenfolge(self, tmp_path):
        einzeln = tmp_path / "einzeln.mp3"
        einzeln.touch()
        ordner = tmp_path / "ordner"
        ordner.mkdir()
        (ordner / "x.mp3").touch()

        playlist = pp.baue_playlist([str(ordner), str(einzeln)])

        assert [p.name for p in playlist] == ["x.mp3", "einzeln.mp3"]

    def test_fehlende_datei_ist_playlistfehler(self, tmp_path):
        with pytest.raises(pp.PlaylistFehler, match="nicht gefunden"):
            pp.baue_playlist([str(tmp_path / "gibtsnicht.mp3")])

    def test_ordner_ohne_mp3s_ist_playlistfehler(self, tmp_path):
        (tmp_path / "nur-text.txt").touch()
        with pytest.raises(pp.PlaylistFehler, match="keine MP3"):
            pp.baue_playlist([str(tmp_path)])


# --- finde_player_backend -----------------------------------------------------

class TestFindePlayerBackend:
    def test_mpv_ist_default_mit_no_video_und_quiet(self):
        backend = pp.finde_player_backend(
            which=lambda name: f"/usr/bin/{name}" if name == "mpv" else None
        )
        assert backend.basis_befehl == ["/usr/bin/mpv", "--no-video", "--really-quiet"]

    def test_mplayer_fallback_wenn_mpv_fehlt(self):
        backend = pp.finde_player_backend(
            which=lambda name: f"/usr/bin/{name}" if name == "mplayer" else None
        )
        assert backend.basis_befehl == ["/usr/bin/mplayer", "-really-quiet"]

    def test_fehler_wenn_kein_player_verfuegbar(self):
        with pytest.raises(pp.PlayerNichtGefunden):
            pp.finde_player_backend(which=lambda name: None)

    def test_override_gewinnt_gegen_erkennung(self):
        backend = pp.finde_player_backend(
            which=lambda name: f"/usr/bin/{name}", override="/opt/fake-player"
        )
        assert backend.basis_befehl == ["/opt/fake-player"]


# --- EventLog -----------------------------------------------------------------

class TestEventLog:
    def test_schreibe_haengt_json_zeile_mit_allen_feldern_an(self, tmp_path):
        pfad = tmp_path / "log.jsonl"
        zeit = dt.datetime(2026, 8, 8, 6, 30, tzinfo=dt.timezone.utc)
        log = pp.EventLog(pfad, uhr=lambda: zeit)

        log.schreibe("start", Path("a.mp3"))
        log.schreibe("ende", Path("a.mp3"), dauer_s=12.3456, detail=None)

        zeilen = [json.loads(z) for z in pfad.read_text(encoding="utf-8").splitlines()]
        assert zeilen[0] == {
            "zeit": "2026-08-08T06:30:00+00:00", "ereignis": "start",
            "datei": "a.mp3", "dauer_s": None, "detail": None,
        }
        assert zeilen[1]["ereignis"] == "ende"
        assert zeilen[1]["dauer_s"] == 12.346  # gerundet auf 3 Stellen

    def test_schreibe_legt_fehlende_ordner_an(self, tmp_path):
        pfad = tmp_path / "Logs" / "tief" / "log.jsonl"
        assert not pfad.parent.exists()

        pp.EventLog(pfad).schreibe("start", "x.mp3")

        assert pfad.exists()
        assert json.loads(pfad.read_text(encoding="utf-8"))["datei"] == "x.mp3"

    def test_schreibe_ueberschreibt_bestehende_eintraege_nicht(self, tmp_path):
        pfad = tmp_path / "log.jsonl"
        pfad.write_text('{"alt": true}\n', encoding="utf-8")

        pp.EventLog(pfad).schreibe("start", "neu.mp3")

        zeilen = pfad.read_text(encoding="utf-8").splitlines()
        assert len(zeilen) == 2
        assert json.loads(zeilen[0]) == {"alt": True}


# --- parse_argumente ----------------------------------------------------------

class TestParseArgumente:
    def test_defaults(self):
        argumente = pp.parse_argumente(["a.mp3"])
        assert argumente.eingaben == ["a.mp3"]
        assert argumente.backend is None
        assert argumente.log_datei is None

    def test_level_wird_als_unbekanntes_argument_abgewiesen(self):
        with pytest.raises(SystemExit) as abbruch:
            pp.parse_argumente(["--level", "35", "a.mp3"])
        assert abbruch.value.code == 2

    def test_ohne_eingaben_bricht_ab(self):
        with pytest.raises(SystemExit) as abbruch:
            pp.parse_argumente([])
        assert abbruch.value.code == 2


# --- Exit-Codes fuer Signale --------------------------------------------------

class TestExitCodeFuerSignal:
    def test_sigint_ergibt_130(self):
        assert pp._exit_code_fuer_signal(signal.SIGINT) == 130

    def test_sigterm_ergibt_143(self):
        assert pp._exit_code_fuer_signal(signal.SIGTERM) == 143


# --- PodcastPlayer (Orchestrierung mit Fakes) ---------------------------------

def baue_player(tmp_path, playlist, backend, uhr=None, **kwargs):
    uhr = uhr or FakeUhr()
    log = pp.EventLog(tmp_path / "log.jsonl", uhr=lambda: dt.datetime(2026, 8, 8, tzinfo=dt.timezone.utc))
    player = pp.PodcastPlayer(
        playlist=playlist, backend=backend, log=log,
        sleep=uhr.sleep, monotonic=uhr.monotonic, **kwargs,
    )
    return player, log


def log_ereignisse(log):
    return [
        (e["ereignis"], e["datei"])
        for e in map(json.loads, log.pfad.read_text(encoding="utf-8").splitlines())
    ]


class TestPodcastPlayer:
    def test_spielt_playlist_in_reihenfolge_und_endet_mit_0(self, tmp_path):
        playlist = [Path("a.mp3"), Path("b.mp3"), Path("c.mp3")]
        backend = FakePlayerBackend()
        player, log = baue_player(tmp_path, playlist, backend)

        exit_code = player.run()

        assert exit_code == 0
        assert backend.gestartete_dateien == playlist
        assert log_ereignisse(log) == [
            ("start", "a.mp3"), ("ende", "a.mp3"),
            ("start", "b.mp3"), ("ende", "b.mp3"),
            ("start", "c.mp3"), ("ende", "c.mp3"),
        ]

    def test_fehlerhafte_datei_setzt_playlist_fort_und_exit_1(self, tmp_path):
        playlist = [Path("a.mp3"), Path("kaputt.mp3"), Path("c.mp3")]
        backend = FakePlayerBackend(exit_codes={"kaputt.mp3": 2})
        player, log = baue_player(tmp_path, playlist, backend)

        exit_code = player.run()

        assert exit_code == 1
        assert backend.gestartete_dateien == playlist  # c.mp3 lief trotzdem
        assert ("fehler", "kaputt.mp3") in log_ereignisse(log)
        assert ("ende", "c.mp3") in log_ereignisse(log)

    def test_laengere_wiedergabe_wartet_bis_zum_ende(self, tmp_path):
        backend = FakePlayerBackend(polls_bis_ende=50)  # "lange" Wiedergabe
        player, log = baue_player(tmp_path, [Path("a.mp3")], backend)

        exit_code = player.run()

        assert exit_code == 0
        assert log_ereignisse(log) == [("start", "a.mp3"), ("ende", "a.mp3")]

    def test_abbruch_beendet_player_und_loggt(self, tmp_path):
        backend = FakePlayerBackend(polls_bis_ende=1000)
        player, log = baue_player(tmp_path, [Path("a.mp3"), Path("b.mp3")], backend)
        backend.bei_start = lambda _d: player.fordere_abbruch_an(signal.SIGINT)

        exit_code = player.run()

        assert exit_code == 130
        assert backend.terminate_aufrufe == 1
        assert backend.gestartete_dateien == [Path("a.mp3")]  # b.mp3 nie gestartet
        assert ("abbruch", "a.mp3") in log_ereignisse(log)

    def test_abbruch_mit_sigterm_ergibt_143(self, tmp_path):
        backend = FakePlayerBackend(polls_bis_ende=1000)
        player, _log = baue_player(tmp_path, [Path("a.mp3")], backend)
        backend.bei_start = lambda _d: player.fordere_abbruch_an(signal.SIGTERM)

        assert player.run() == 143

    def test_nicht_startbarer_player_wird_als_fehler_geloggt(self, tmp_path):
        class KaputtesBackend(FakePlayerBackend):
            def start(self, datei):
                super().start(datei)
                raise OSError("kein Player")

        player, log = baue_player(tmp_path, [Path("a.mp3")], KaputtesBackend())

        exit_code = player.run()

        assert exit_code == 1
        assert log_ereignisse(log) == [("start", "a.mp3"), ("fehler", "a.mp3")]
