"""Unit-Tests fuer podcast_player (R00002) — reine Logik, keine Subprozesse."""

from __future__ import annotations

import datetime as dt
import json
import signal
from pathlib import Path

import pytest
from conftest import FakeAudioMixer, FakePlayerBackend, FakeUhr

import podcast_player as pp


# --- parse_spotify_sink_inputs ----------------------------------------------

PACTL_AUSGABE_GEMISCHT = """\
Sink Input #42
\tDriver: protocol-native.c
\tVolume: front-left: 65536 / 100% / 0.00 dB,   front-right: 65536 / 100% / 0.00 dB
\tProperties:
\t\tapplication.name = "Spotify"
\t\tmedia.name = "Track A"
Sink Input #43
\tDriver: protocol-native.c
\tVolume: front-left: 39322 /  60% / -13.31 dB,   front-right: 39322 /  60% / -13.31 dB
\tProperties:
\t\tapplication.name = "Firefox"
Sink Input #44
\tVolume: front-left: 13107 /  20% / -41.94 dB
\tProperties:
\t\tapplication.name = "spotify"
"""


class TestParseSpotifySinkInputs:
    def test_findet_nur_spotify_inputs_case_insensitive(self):
        inputs = pp.parse_spotify_sink_inputs(PACTL_AUSGABE_GEMISCHT)
        assert inputs == {42: 100, 44: 20}

    def test_fremde_anwendung_wird_ignoriert(self):
        inputs = pp.parse_spotify_sink_inputs(PACTL_AUSGABE_GEMISCHT)
        assert 43 not in inputs

    def test_leere_ausgabe_ergibt_leeres_dict(self):
        assert pp.parse_spotify_sink_inputs("") == {}

    def test_block_ohne_volume_wird_uebersprungen(self):
        ausgabe = 'Sink Input #7\n\tapplication.name = "spotify"\n'
        assert pp.parse_spotify_sink_inputs(ausgabe) == {}


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


# --- FadeDuckingStrategy ------------------------------------------------------

def strategie(mixer, level=20):
    return pp.FadeDuckingStrategy(mixer, duck_level=level, sleep=lambda _s: None)


class TestFadeDuckingStrategy:
    def test_start_senkt_alle_inputs_auf_duck_level(self):
        mixer = FakeAudioMixer({10: 100, 11: 80})
        ducking = strategie(mixer)

        ducking.start()

        assert mixer.inputs == {10: 20, 11: 20}
        assert ducking.gemerkte_originale == {10: 100, 11: 80}

    def test_fade_verlaeuft_in_10_monoton_fallenden_schritten(self):
        mixer = FakeAudioMixer({10: 100})

        strategie(mixer).start()

        werte = [v for (sid, v) in mixer.set_volume_aufrufe if sid == 10]
        assert len(werte) == 10
        assert werte == sorted(werte, reverse=True)
        assert werte[-1] == 20

    def test_start_ohne_spotify_setzt_keine_lautstaerke(self):
        mixer = FakeAudioMixer({})

        ducking = strategie(mixer)
        ducking.start()

        assert mixer.set_volume_aufrufe == []
        assert ducking.gemerkte_originale == {}

    def test_poll_duckt_neuen_input_und_merkt_original(self):
        mixer = FakeAudioMixer({10: 100})
        ducking = strategie(mixer)
        ducking.start()

        mixer.inputs[55] = 90  # neuer Stream (Titelwechsel)
        ducking.poll()

        assert mixer.inputs[55] == 20
        assert ducking.gemerkte_originale[55] == 90

    def test_poll_laesst_bereits_geduckte_inputs_unangetastet(self):
        mixer = FakeAudioMixer({10: 100})
        ducking = strategie(mixer)
        ducking.start()
        aufrufe_vorher = len(mixer.set_volume_aufrufe)

        ducking.poll()  # nichts Neues

        assert len(mixer.set_volume_aufrufe) == aufrufe_vorher

    def test_poll_vergisst_verschwundene_inputs(self):
        mixer = FakeAudioMixer({10: 100, 11: 80})
        ducking = strategie(mixer)
        ducking.start()

        del mixer.inputs[11]
        ducking.poll()

        assert ducking.gemerkte_originale == {10: 100}

    def test_stop_stellt_originale_wieder_her(self):
        mixer = FakeAudioMixer({10: 100, 11: 80})
        ducking = strategie(mixer)
        ducking.start()

        ducking.stop()

        assert mixer.inputs == {10: 100, 11: 80}
        assert ducking.gemerkte_originale == {}

    def test_stop_stellt_auch_spaeter_aufgetauchte_inputs_wieder_her(self):
        mixer = FakeAudioMixer({10: 100})
        ducking = strategie(mixer)
        ducking.start()
        mixer.inputs[55] = 90
        ducking.poll()

        ducking.stop()

        assert mixer.inputs == {10: 100, 55: 90}

    def test_stop_ueberspringt_inzwischen_verschwundene_inputs(self):
        mixer = FakeAudioMixer({10: 100, 11: 80})
        ducking = strategie(mixer)
        ducking.start()
        del mixer.inputs[11]
        aufrufe_vorher = len(mixer.set_volume_aufrufe)

        ducking.stop()

        assert mixer.inputs == {10: 100}
        ids_beim_stop = {sid for sid, _v in mixer.set_volume_aufrufe[aufrufe_vorher:]}
        assert ids_beim_stop == {10}

    def test_eigenes_duck_level_wird_verwendet(self):
        mixer = FakeAudioMixer({10: 100})

        strategie(mixer, level=35).start()

        assert mixer.inputs[10] == 35


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
        assert argumente.level == 20
        assert argumente.backend is None
        assert argumente.log_datei is None
        assert argumente.poll_intervall == 2.0
        assert argumente.fade_delay == 0.08

    def test_level_wird_uebernommen(self):
        assert pp.parse_argumente(["--level", "35", "a.mp3"]).level == 35

    @pytest.mark.parametrize("level", ["-1", "101"])
    def test_level_ausserhalb_0_bis_100_bricht_ab(self, level):
        with pytest.raises(SystemExit) as abbruch:
            pp.parse_argumente(["--level", level, "a.mp3"])
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

def baue_player(tmp_path, playlist, backend, mixer=None, uhr=None, **kwargs):
    uhr = uhr or FakeUhr()
    mixer = mixer if mixer is not None else FakeAudioMixer({})
    ducking = pp.FadeDuckingStrategy(mixer, sleep=lambda _s: None)
    log = pp.EventLog(tmp_path / "log.jsonl", uhr=lambda: dt.datetime(2026, 8, 8, tzinfo=dt.timezone.utc))
    player = pp.PodcastPlayer(
        playlist=playlist, backend=backend, ducking=ducking, log=log,
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

    def test_ducking_haelt_ueber_gesamte_playlist(self, tmp_path):
        mixer = FakeAudioMixer({10: 100})
        zwischenstaende = []
        backend = FakePlayerBackend(
            bei_start=lambda _d: zwischenstaende.append(dict(mixer.inputs))
        )
        player, _log = baue_player(
            tmp_path, [Path("a.mp3"), Path("b.mp3")], backend, mixer=mixer
        )

        exit_code = player.run()

        assert exit_code == 0
        # Beim Start JEDER Datei war der Input geduckt — kein Hochstellen dazwischen.
        assert zwischenstaende == [{10: 20}, {10: 20}]
        # Erst nach der letzten Datei wird das Original wiederhergestellt.
        assert mixer.inputs == {10: 100}

    def test_ueberwachung_pollt_ducking_im_intervall(self, tmp_path):
        mixer = FakeAudioMixer({10: 100})
        backend = FakePlayerBackend(polls_bis_ende=50)  # "lange" Wiedergabe
        player, _log = baue_player(
            tmp_path, [Path("a.mp3")], backend, mixer=mixer,
            poll_interval_s=2.0, warte_schritt_s=0.1,
        )

        def neuer_stream_nach_erstem_poll(_datei):
            mixer.inputs[55] = 90

        backend.bei_start = neuer_stream_nach_erstem_poll

        player.run()

        # Der neue Stream wurde waehrend der Wiedergabe geduckt (nicht erst am Ende):
        duck_aufrufe_55 = [(s, v) for (s, v) in mixer.set_volume_aufrufe if s == 55 and v == 20]
        assert duck_aufrufe_55, "neuer Sink-Input wurde nicht geduckt"
        # und am Ende wieder auf sein Original zurueckgestellt:
        assert mixer.inputs[55] == 90

    def test_abbruch_beendet_player_stellt_lautstaerke_her_und_loggt(self, tmp_path):
        mixer = FakeAudioMixer({10: 100})
        backend = FakePlayerBackend(polls_bis_ende=1000)
        player, log = baue_player(
            tmp_path, [Path("a.mp3"), Path("b.mp3")], backend, mixer=mixer
        )
        backend.bei_start = lambda _d: player.fordere_abbruch_an(signal.SIGINT)

        exit_code = player.run()

        assert exit_code == 130
        assert backend.terminate_aufrufe == 1
        assert mixer.inputs == {10: 100}  # wiederhergestellt
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
