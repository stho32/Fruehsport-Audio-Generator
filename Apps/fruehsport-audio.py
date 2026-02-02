#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "openai>=1.0.0",
#     "pydub>=0.25.1",
#     "audioop-lts>=0.2.1; python_version>='3.13'",
# ]
# ///

"""
fruehsport-audio: Konvertiert Frühsport-Anleitungsskripte zu MP3-Audiodateien.

Unterstützt #PAUSE X Anweisungen für kontrollierte Pausen (Stille).
Unterstützt #INCLUDE datei.mp3 zum Einbinden externer Audio-Dateien.

Anforderungen: siehe ../Anforderungen/fruehsport-audio.md
"""

import asyncio
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from openai import AsyncOpenAI
from pydub import AudioSegment


def check_ffmpeg() -> None:
    """Prüft ob ffmpeg installiert ist (benötigt von pydub)."""
    if shutil.which("ffmpeg") is None:
        print("FEHLER: ffmpeg ist nicht installiert.")
        print()
        print("ffmpeg wird für die Audio-Verarbeitung benötigt.")
        print("Installation:")
        print("  Ubuntu/Debian: sudo apt install ffmpeg")
        print("  Fedora:        sudo dnf install ffmpeg")
        print("  Arch:          sudo pacman -S ffmpeg")
        print("  macOS:         brew install ffmpeg")
        print("  Windows:       https://ffmpeg.org/download.html")
        sys.exit(1)

# Konfiguration
MAX_CHUNK_SIZE = 4000  # OpenAI TTS Limit
CONCURRENT_REQUESTS = 5  # Maximale parallele API-Anfragen
VOICE = "nova"  # Motivierende Stimme für Sport-Anleitung
PRIMARY_MODEL = "gpt-4o-mini-tts"
FALLBACK_MODEL = "tts-1"

# Pfade relativ zum Script
SCRIPT_DIR = Path(__file__).parent
SKRIPTE_DIR = SCRIPT_DIR.parent / "Skripte"

# Regex für Pause-Anweisung
PAUSE_PATTERN = re.compile(r"^#PAUSE\s+(\d+)\s*$", re.MULTILINE | re.IGNORECASE)

# Regex für Include-Anweisung
INCLUDE_PATTERN = re.compile(r"^#INCLUDE\s+(.+?)\s*$", re.MULTILINE | re.IGNORECASE)

# Regex für Start-Marker (alles darüber wird ignoriert, z.B. Materiallisten)
START_PATTERN = re.compile(r"^#START\s*$", re.MULTILINE | re.IGNORECASE)


@dataclass
class Segment:
    """Ein Segment im Skript - Text, Pause oder Include."""
    content: str | int  # Text, Pausendauer in Sekunden, oder Dateiname
    is_pause: bool
    is_include: bool = False


def get_md_files() -> list[Path]:
    """Findet alle Markdown-Dateien im Skripte-Verzeichnis."""
    if not SKRIPTE_DIR.exists():
        SKRIPTE_DIR.mkdir(parents=True)
        return []
    return sorted(SKRIPTE_DIR.glob("*.md"))


def get_missing_mp3s(md_files: list[Path]) -> list[Path]:
    """Filtert MD-Dateien, die noch keine zugehörige MP3 haben."""
    missing = []
    for md_file in md_files:
        mp3_file = md_file.with_suffix(".mp3")
        if not mp3_file.exists():
            missing.append(md_file)
    return missing


def parse_script(text: str) -> list[Segment]:
    """Parst ein Skript und extrahiert Text-Segmente, Pausen und Includes."""
    segments: list[Segment] = []

    # Falls #START vorhanden, nur den Teil danach verwenden
    start_match = START_PATTERN.search(text)
    if start_match:
        text = text[start_match.end():]

    # Alle Direktiven mit Positionen finden
    directives = []
    for m in PAUSE_PATTERN.finditer(text):
        directives.append((m.start(), m.end(), "pause", int(m.group(1))))
    for m in INCLUDE_PATTERN.finditer(text):
        directives.append((m.start(), m.end(), "include", m.group(1)))
    directives.sort(key=lambda x: x[0])

    # Text zwischen Direktiven verarbeiten
    pos = 0
    for start, end, dtype, value in directives:
        text_before = text[pos:start].strip()
        if text_before:
            segments.append(Segment(content=text_before, is_pause=False))

        if dtype == "pause":
            if value > 0:
                segments.append(Segment(content=value, is_pause=True))
        elif dtype == "include":
            segments.append(Segment(content=value, is_pause=False, is_include=True))

        pos = end

    # Restlicher Text nach der letzten Direktive
    remaining = text[pos:].strip()
    if remaining:
        segments.append(Segment(content=remaining, is_pause=False))

    return segments


def split_text_into_chunks(text: str) -> list[str]:
    """Teilt langen Text in Chunks auf (max. 4000 Zeichen)."""
    if len(text) <= MAX_CHUNK_SIZE:
        return [text]

    paragraphs = text.split("\n\n")
    chunks = []
    current_chunk = ""

    for paragraph in paragraphs:
        if len(paragraph) > MAX_CHUNK_SIZE:
            if current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = ""
            # Paragraph in Sätze aufteilen
            sentences = paragraph.replace(". ", ".\n").split("\n")
            for sentence in sentences:
                if len(current_chunk) + len(sentence) + 1 > MAX_CHUNK_SIZE:
                    if current_chunk:
                        chunks.append(current_chunk.strip())
                    current_chunk = sentence + " "
                else:
                    current_chunk += sentence + " "
        elif len(current_chunk) + len(paragraph) + 2 > MAX_CHUNK_SIZE:
            chunks.append(current_chunk.strip())
            current_chunk = paragraph + "\n\n"
        else:
            current_chunk += paragraph + "\n\n"

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks


async def text_to_speech(
    client: AsyncOpenAI,
    text: str,
    output_file: Path,
    model: str = PRIMARY_MODEL,
) -> None:
    """Konvertiert Text zu MP3 mit OpenAI TTS API."""
    try:
        async with client.audio.speech.with_streaming_response.create(
            model=model,
            voice=VOICE,
            input=text,
            response_format="mp3",
        ) as response:
            with open(output_file, "wb") as f:
                async for chunk in response.iter_bytes():
                    f.write(chunk)
    except Exception as e:
        # Fallback auf tts-1 wenn das primäre Modell nicht verfügbar ist
        if model == PRIMARY_MODEL and "model" in str(e).lower():
            print(f"      Fallback auf {FALLBACK_MODEL}...")
            await text_to_speech(client, text, output_file, FALLBACK_MODEL)
        else:
            raise


def create_silence(duration_seconds: int, output_file: Path) -> None:
    """Erzeugt eine MP3-Datei mit Stille der angegebenen Dauer."""
    silence = AudioSegment.silent(duration=duration_seconds * 1000)  # ms
    silence.export(output_file, format="mp3")


def combine_audio_files(audio_files: list[Path], output_file: Path) -> None:
    """Kombiniert mehrere MP3-Dateien zu einer."""
    if not audio_files:
        return

    combined = AudioSegment.from_mp3(audio_files[0])
    for audio_file in audio_files[1:]:
        audio = AudioSegment.from_mp3(audio_file)
        combined += audio

    combined.export(output_file, format="mp3")


async def convert_script_to_mp3(client: AsyncOpenAI, md_file: Path) -> bool:
    """Konvertiert ein Frühsport-Skript zu MP3."""
    text = md_file.read_text(encoding="utf-8")
    if not text.strip():
        print(f"  - Datei ist leer, überspringe")
        return False

    segments = parse_script(text)
    text_segments = [s for s in segments if not s.is_pause and not s.is_include]
    pause_segments = [s for s in segments if s.is_pause]
    include_segments = [s for s in segments if s.is_include]

    include_info = f", {len(include_segments)} Include(s)" if include_segments else ""
    print(f"  - Segmente: {len(segments)} ({len(text_segments)} Sprache, {len(pause_segments)} Pausen{include_info})")
    print(f"  - Stimme: {VOICE}")

    # Temporäres Verzeichnis für Segmente
    temp_dir = SKRIPTE_DIR / "temp_audio"
    temp_dir.mkdir(exist_ok=True)

    # Semaphore für parallele Verarbeitung
    semaphore = asyncio.Semaphore(CONCURRENT_REQUESTS)
    audio_files: list[Path] = []

    async def process_text_segment(idx: int, text_content: str) -> list[Path]:
        """Verarbeitet ein Text-Segment (eventuell in mehreren Chunks)."""
        async with semaphore:
            chunks = split_text_into_chunks(text_content)
            chunk_files = []

            for chunk_idx, chunk in enumerate(chunks):
                chunk_file = temp_dir / f"segment_{idx:04d}_chunk_{chunk_idx:04d}.mp3"
                await text_to_speech(client, chunk, chunk_file)
                chunk_files.append(chunk_file)

            return chunk_files

    print(f"  - Verarbeite Segmente...")

    # Segmente sequenziell verarbeiten (Reihenfolge wichtig!)
    for idx, segment in enumerate(segments):
        if segment.is_pause:
            # Stille erzeugen
            pause_file = temp_dir / f"segment_{idx:04d}_pause.mp3"
            create_silence(segment.content, pause_file)
            audio_files.append(pause_file)
        elif segment.is_include:
            # Externe MP3-Datei einbinden
            include_file = SKRIPTE_DIR / segment.content
            if include_file.exists():
                audio_files.append(include_file)
                print(f"    Include: {segment.content}")
            else:
                print(f"    WARNUNG: Include-Datei nicht gefunden: {segment.content}")
        else:
            # Text-Segment(e) verarbeiten
            chunk_files = await process_text_segment(idx, segment.content)
            audio_files.extend(chunk_files)

    # Alle Segmente zusammenfügen
    output_file = md_file.with_suffix(".mp3")
    if len(audio_files) == 1:
        shutil.move(audio_files[0], output_file)
    else:
        combine_audio_files(audio_files, output_file)
        # Temporäre Dateien löschen (keine Include-Dateien!)
        for audio_file in audio_files:
            if audio_file.exists() and audio_file.parent == temp_dir:
                audio_file.unlink()

    # Temporäres Verzeichnis aufräumen
    if temp_dir.exists() and not any(temp_dir.iterdir()):
        temp_dir.rmdir()

    print(f"  - MP3 erstellt: {output_file.name}")
    return True


async def main():
    check_ffmpeg()
    print(f"Suche nach Skripten in {SKRIPTE_DIR.name}/...")

    md_files = get_md_files()
    if not md_files:
        print("Keine Skripte gefunden.")
        print(f"Lege Frühsport-Skripte in {SKRIPTE_DIR} ab.")
        return

    missing = get_missing_mp3s(md_files)
    already_converted = len(md_files) - len(missing)

    print(f"Gefunden: {len(md_files)} Skript(e)")
    print(f"Bereits konvertiert: {already_converted} Datei(en)")
    print(f"Zu konvertieren: {len(missing)} Datei(en)")

    if not missing:
        print("\nAlle Skripte sind bereits konvertiert.")
        return

    print()

    client = AsyncOpenAI()
    converted = 0

    for i, md_file in enumerate(missing, 1):
        print(f"[{i}/{len(missing)}] Konvertiere: {md_file.name}")
        try:
            if await convert_script_to_mp3(client, md_file):
                converted += 1
        except Exception as e:
            print(f"  - FEHLER: {e}")

        print()

    print(f"Fertig! {converted} Datei(en) konvertiert.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nAbgebrochen.")
        sys.exit(1)
