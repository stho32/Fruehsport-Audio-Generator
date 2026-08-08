"""Gemeinsame Test-Infrastruktur fuer R00002 (podcast_player).

Macht das Modul ``Apps/podcast_player.py`` importierbar und stellt Fakes
bereit, die echte Zustandsuebergaenge abbilden (Skill test-ehrlichkeit):
kein echter pactl-, mpv- oder mplayer-Aufruf in der gesamten Suite.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJEKT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJEKT_ROOT / "Apps"))

from podcast_player import AudioMixer, PlayerBackend  # noqa: E402


class FakeAudioMixer(AudioMixer):
    """AudioMixer-Fake mit echtem Zustand: Sink-Inputs als dict id -> Volumen%.

    ``set_volume`` veraendert den Zustand wirklich und protokolliert jeden
    Aufruf, damit Tests Vorher/Nachher und Fade-Verlaeufe pruefen koennen.
    """

    def __init__(self, inputs: dict[int, int] | None = None) -> None:
        self.inputs: dict[int, int] = dict(inputs or {})
        self.set_volume_aufrufe: list[tuple[int, int]] = []

    def list_spotify_inputs(self) -> dict[int, int]:
        return dict(self.inputs)

    def set_volume(self, sink_input_id: int, prozent: int) -> None:
        self.set_volume_aufrufe.append((sink_input_id, prozent))
        if sink_input_id in self.inputs:
            self.inputs[sink_input_id] = prozent


class FakePlayerBackend(PlayerBackend):
    """PlayerBackend-Fake mit echtem Lebenszyklus (gestartet -> beendet).

    - ``exit_codes``: Abbildung Dateiname -> Exit-Code (Default 0).
    - ``polls_bis_ende``: wie oft ``poll()`` None liefert, bevor der
      hinterlegte Exit-Code zurueckkommt (simuliert Spieldauer).
    - ``bei_start``: optionaler Hook (datei -> None), z.B. um waehrend der
      "Wiedergabe" einen neuen Spotify-Stream im FakeAudioMixer auftauchen
      zu lassen.
    """

    def __init__(
        self,
        exit_codes: dict[str, int] | None = None,
        polls_bis_ende: int = 0,
        bei_start=None,
    ) -> None:
        self.exit_codes = exit_codes or {}
        self.polls_bis_ende = polls_bis_ende
        self.bei_start = bei_start
        self.gestartete_dateien: list[Path] = []
        self.terminate_aufrufe = 0
        self._laufende_datei: Path | None = None
        self._verbleibende_polls = 0

    def start(self, datei: Path) -> None:
        self.gestartete_dateien.append(datei)
        self._laufende_datei = datei
        self._verbleibende_polls = self.polls_bis_ende
        if self.bei_start is not None:
            self.bei_start(datei)

    def poll(self) -> int | None:
        if self._laufende_datei is None:
            return None
        if self._verbleibende_polls > 0:
            self._verbleibende_polls -= 1
            return None
        datei = self._laufende_datei
        self._laufende_datei = None
        return self.exit_codes.get(datei.name, 0)

    def terminate(self) -> None:
        self.terminate_aufrufe += 1
        self._laufende_datei = None


class FakeUhr:
    """Deterministische monotone Uhr; ``sleep`` rueckt die Zeit vor."""

    def __init__(self, start: float = 0.0) -> None:
        self.jetzt = start

    def monotonic(self) -> float:
        return self.jetzt

    def sleep(self, sekunden: float) -> None:
        self.jetzt += sekunden
