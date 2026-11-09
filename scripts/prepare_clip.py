#!/usr/bin/env python3
"""Create a ClipScribe-ready video, word-timed subtitles, and manifest entry.

The script intentionally keeps all generated assets in ../clips, making them
available to the static web application when it is served from the project root.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent.parent
CLIPS_DIR = ROOT / "clips"
MANIFEST_PATH = CLIPS_DIR / "manifest.json"
COMMON_ABBREVIATIONS = {
    "mr.", "mrs.", "ms.", "dr.", "st.", "capt.", "sgt.", "prof.",
    "jr.", "sr.", "vs.", "etc.", "u.s.", "u.k.",
}


def log_step(message: str) -> None:
    stamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{stamp}] [ClipScribe] {message}", flush=True)


def bootstrap_venv() -> None:
    """Re-exec in the project venv so direct CLI use cannot miss dependencies."""
    venv_python = ROOT / ".venv" / "bin" / "python"
    if venv_python.is_file() and Path(sys.executable).absolute() != venv_python.absolute():
        os.execv(str(venv_python), [str(venv_python), *sys.argv])


@dataclass(frozen=True)
class TimedWord:
    text: str
    start: float
    end: float


def parse_time(value: str) -> float:
    """Accept seconds or HH:MM:SS(.mmm) / MM:SS(.mmm) timestamps."""
    try:
        return float(value)
    except ValueError:
        pass
    parts = value.strip().split(":")
    if len(parts) not in (2, 3):
        raise argparse.ArgumentTypeError("Use seconds, MM:SS, or HH:MM:SS.")
    try:
        values = [float(part) for part in parts]
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"Tempo inválido: {value}") from error
    if any(part < 0 for part in values):
        raise argparse.ArgumentTypeError("O tempo não pode ser negativo.")
    return values[-1] + values[-2] * 60 + (values[-3] * 3600 if len(values) == 3 else 0)


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug or "clip"


def run(command: list[str]) -> None:
    try:
        subprocess.run(command, check=True)
    except FileNotFoundError as error:
        raise RuntimeError("ffmpeg/ffprobe não encontrado. Instale o ffmpeg e tente novamente.") from error
    except subprocess.CalledProcessError as error:
        raise RuntimeError(f"Comando falhou ({error.returncode}): {' '.join(command)}") from error


def ensure_ffmpeg() -> None:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError("ffmpeg e ffprobe são obrigatórios. Consulte o README para instalação.")


def make_video(source: Path, destination: Path, start: float | None, end: float | None) -> None:
    """Encode a browser-compatible MP4, optionally cutting relative to the source."""
    command = ["ffmpeg", "-y", "-nostats", "-loglevel", "error"]
    if start is not None:
        command += ["-ss", f"{start:.3f}"]
    command += ["-i", str(source)]
    if end is not None:
        if start is not None:
            command += ["-t", f"{end - start:.3f}"]
        else:
            command += ["-t", f"{end:.3f}"]
    command += ["-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", "-movflags", "+faststart", str(destination)]
    run(command)


def probe_duration(path: Path) -> float:
    output = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)], text=True)
    return round(float(output.strip()), 3)


def decode_audio_for_whisper(video_path: Path):
    """Decode through the system FFmpeg, avoiding PyAV ABI differences on Linux."""
    import numpy as np

    command = ["ffmpeg", "-nostats", "-loglevel", "error", "-i", str(video_path), "-f", "s16le", "-ac", "1", "-ar", "16000", "pipe:1"]
    completed = subprocess.run(command, capture_output=True)
    if completed.returncode:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Não foi possível decodificar áudio para Whisper: {detail}")
    return np.frombuffer(completed.stdout, np.int16).astype("float32") / 32768.0


def transcribe(video_path: Path, model_name: str, initial_prompt: str | None = None, progress_callback=None) -> list[TimedWord]:
    """Use faster-whisper first; openai-whisper is a compatible fallback."""
    words: list[TimedWord] = []
    next_progress = 120.0
    try:
        from faster_whisper import WhisperModel  # type: ignore

        model = WhisperModel(model_name, device="cpu", compute_type="int8")
        segments, _info = model.transcribe(decode_audio_for_whisper(video_path), language="en", word_timestamps=True, initial_prompt=initial_prompt)
        for segment in segments:
            for word in segment.words or []:
                if word.start is not None and word.end is not None and word.word.strip():
                    words.append(TimedWord(word.word.strip(), float(word.start), float(word.end)))
            segment_end = float(getattr(segment, "end", 0.0) or 0.0)
            if progress_callback and segment_end >= next_progress:
                progress_callback(segment_end)
                next_progress += 120.0
        return words
    except ImportError:
        pass

    try:
        import whisper  # type: ignore
    except ImportError as error:
        raise RuntimeError("Instale faster-whisper (recomendado) ou openai-whisper para transcrever.") from error
    model = whisper.load_model(model_name)
    result = model.transcribe(str(video_path), language="en", word_timestamps=True, verbose=False, initial_prompt=initial_prompt)
    for segment in result.get("segments", []):
        for word in segment.get("words", []):
            if word.get("word", "").strip():
                words.append(TimedWord(word["word"].strip(), float(word["start"]), float(word["end"])))
        if progress_callback and float(segment.get("end", 0.0)) >= next_progress:
            progress_callback(float(segment["end"])); next_progress += 120.0
    return words


def has_strong_punctuation(word: TimedWord) -> bool:
    text = word.text.strip().lower().rstrip("\"'”’)]}")
    if text in COMMON_ABBREVIATIONS or re.fullmatch(r"(?:[a-z]\.){2,}", text):
        return False
    return text.endswith((".", "?", "!", "…"))


def has_weak_punctuation(word: TimedWord) -> bool:
    return word.text.rstrip().endswith((",", ";", ":"))


def starts_lowercase(block: list[TimedWord]) -> bool:
    return bool(block and re.match(r"^[a-z]", block[0].text.strip()))


def merge_orphan_segments(blocks: list[list[TimedWord]]) -> list[list[TimedWord]]:
    """Rejoin short/direct continuations created by acoustic pauses."""
    merged: list[list[TimedWord]] = []
    index = 0
    while index < len(blocks):
        current = list(blocks[index])
        while index + 1 < len(blocks) and not has_strong_punctuation(current[-1]):
            following = blocks[index + 1]
            gap = following[0].start - current[-1].end
            direct_continuation = starts_lowercase(following) and gap < 0.6
            if len(following) > 4 and not direct_continuation:
                break
            current.extend(following)
            index += 1
        merged.append(current)
        index += 1
    return merged


def split_long_sentence(block: list[TimedWord], max_words: int) -> list[list[TimedWord]]:
    """Split only long sentences, keeping at least five words on each side."""
    if len(block) <= 16:
        return [block]
    candidates = [index + 1 for index, word in enumerate(block[:-1]) if has_weak_punctuation(word)]
    safe = [position for position in candidates if position >= 5 and len(block) - position >= 5]
    if safe:
        position = min(safe, key=lambda value: abs(value - min(max_words, len(block) / 2)))
        return split_long_sentence(block[:position], max_words) + split_long_sentence(block[position:], max_words)
    if len(block) <= max_words:
        return [block]
    position = min(max_words, len(block) - 5)
    if position < 5:
        return [block]
    return [block[:position], *split_long_sentence(block[position:], max_words)]


def segment_words(words: Iterable[TimedWord], max_words: int = 18) -> list[list[TimedWord]]:
    """Build complete sentences; the word limit is only an emergency fallback."""
    base: list[list[TimedWord]] = []
    block: list[TimedWord] = []
    for word in words:
        if block and word.start - block[-1].end >= 1.1:
            base.append(block); block = []
        block.append(word)
        if has_strong_punctuation(word):
            base.append(block); block = []
    if block:
        base.append(block)
    result: list[list[TimedWord]] = []
    for sentence in merge_orphan_segments(base):
        result.extend(split_long_sentence(sentence, max(18, max_words)))
    return result


def vtt_time(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    secs, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02}.{milliseconds:03}"


def srt_time(seconds: float) -> str:
    return vtt_time(seconds).replace(".", ",")


def write_subtitles(blocks: list[list[TimedWord]], vtt_path: Path, srt_path: Path) -> None:
    vtt_lines = ["WEBVTT", ""]
    srt_lines: list[str] = []
    for index, block in enumerate(blocks, start=1):
        start = block[0].start
        next_start = blocks[index][0].start if index < len(blocks) else None
        end = block[-1].end + 0.08
        if next_start is not None:
            end = min(end, max(block[-1].end, next_start - 0.01))
        text = " ".join(word.text for word in block)
        vtt_lines += [f"{vtt_time(start)} --> {vtt_time(end)}", text, ""]
        srt_lines += [str(index), f"{srt_time(start)} --> {srt_time(end)}", text, ""]
    vtt_path.write_text("\n".join(vtt_lines), encoding="utf-8")
    srt_path.write_text("\n".join(srt_lines), encoding="utf-8")


def update_manifest(entry: dict[str, object]) -> None:
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    data: dict[str, list[dict[str, object]]] = {"clips": []}
    if MANIFEST_PATH.exists():
        try:
            data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
            if not isinstance(data.get("clips"), list):
                raise ValueError("A chave clips precisa ser uma lista")
        except (json.JSONDecodeError, ValueError) as error:
            raise RuntimeError(f"Manifest inválido: {MANIFEST_PATH}") from error
    clips = [clip for clip in data["clips"] if clip.get("id") != entry["id"]]
    clips.append(entry); data["clips"] = clips
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=CLIPS_DIR, suffix=".json") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2); handle.write("\n"); temporary = Path(handle.name)
    temporary.replace(MANIFEST_PATH)


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Recorta, transcreve e cadastra um clipe para o ClipScribe.")
    parser.add_argument("--input", required=True, type=Path, help="Vídeo de origem (.mp4, .mkv, etc.)")
    parser.add_argument("--start", type=parse_time, help="Início em segundos, MM:SS ou HH:MM:SS")
    parser.add_argument("--end", type=parse_time, help="Fim em segundos, MM:SS ou HH:MM:SS")
    parser.add_argument("--title", required=True, help="Título amigável do clipe")
    parser.add_argument("--model", default="base.en", help="Modelo Whisper (padrão: base.en)")
    parser.add_argument("--max-words", type=int, default=18, help="Limite de segurança para frases sem pontuação (padrão: 18)")
    parser.add_argument("--transcript-file", type=Path, help="Transcript oficial opcional para alinhamento léxico")
    args = parser.parse_args()
    if not args.input.is_file(): parser.error(f"Arquivo não encontrado: {args.input}")
    if args.max_words < 1: parser.error("--max-words deve ser ao menos 1")
    if args.end is not None and args.start is not None and args.end <= args.start: parser.error("--end deve ser maior que --start")
    if args.transcript_file is not None and not args.transcript_file.is_file(): parser.error(f"Transcript não encontrado: {args.transcript_file}")
    return args


def main() -> int:
    args = arguments(); ensure_ffmpeg(); CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    slug = slugify(args.title); video_path = CLIPS_DIR / f"{slug}.mp4"; vtt_path = CLIPS_DIR / f"{slug}.vtt"; srt_path = CLIPS_DIR / f"{slug}.srt"
    size_mb = args.input.stat().st_size / (1024 * 1024)
    log_step(f"[1/5] Recebido vídeo: {args.input.name} ({size_mb:.1f} MB) | Modo: Clipe único")
    log_step("[2/5] Extraindo/convertendo vídeo com FFmpeg para transcrição..."); make_video(args.input.resolve(), video_path, args.start, args.end)
    reference = args.transcript_file.read_text(encoding="utf-8") if args.transcript_file else ""
    initial_prompt = None
    if reference:
        # Imported lazily: align_transcript imports TimedWord from this module.
        from align_transcript import align_words, initial_prompt_from_reference
        initial_prompt = initial_prompt_from_reference(reference)
    duration = probe_duration(video_path)
    def progress(seconds: float) -> None:
        log_step(f"... transcrito até {int(seconds // 60):02}:{int(seconds % 60):02} / {int(duration // 60):02}:{int(duration % 60):02}")
    log_step(f"[3/5] Transcrevendo com Faster-Whisper (modelo: {args.model}) — progresso a cada ~2 minutos...")
    words = transcribe(video_path, args.model, initial_prompt=initial_prompt, progress_callback=progress)
    if not words: raise RuntimeError("A transcrição não retornou palavras com timestamps.")
    corrections = 0
    if reference:
        from align_transcript import align_words_with_stats
        words, stats = align_words_with_stats(words, reference); corrections = stats.corrections
    log_step(f"[4/5] Alinhando transcript e montando sentenças completas ({len(words)} palavras, {corrections} correções)...")
    blocks = segment_words(words, args.max_words); write_subtitles(blocks, vtt_path, srt_path)
    entry = {"id": slug, "title": args.title, "videoUrl": f"clips/{video_path.name}", "subtitleUrl": f"clips/{vtt_path.name}", "duration": probe_duration(video_path), "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
    update_manifest(entry); log_step(f"[5/5] ✅ Importação concluída: {len(blocks)} sentenças em {video_path.name}")
    return 0


if __name__ == "__main__":
    bootstrap_venv()
    try: raise SystemExit(main())
    except RuntimeError as error: print(f"Erro: {error}", file=sys.stderr); raise SystemExit(1)
