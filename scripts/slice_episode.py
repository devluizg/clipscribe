#!/usr/bin/env python3
"""Transcribe an episode once, then cut natural ~two-minute ClipScribe chapters."""
from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from align_transcript import align_words_with_stats, initial_prompt_from_reference
from prepare_clip import CLIPS_DIR, MANIFEST_PATH, TimedWord, bootstrap_venv, ensure_ffmpeg, has_strong_punctuation, log_step, make_video, probe_duration, segment_words, slugify, transcribe, write_subtitles


def chapters(blocks: list[list[TimedWord]], target: float) -> list[list[list[TimedWord]]]:
    """Cut exclusively after complete sentences near the requested duration."""
    result = []; start = 0
    while start < len(blocks):
        chapter_start = blocks[start][0].start
        candidates = [index for index in range(start, len(blocks)) if has_strong_punctuation(blocks[index][-1])]
        if not candidates:
            result.append(blocks[start:]); break
        lower = chapter_start + max(30, target - 20)
        upper = chapter_start + target + 45
        in_window = [index for index in candidates if lower <= blocks[index][-1].end <= upper]
        if in_window:
            end = min(in_window, key=lambda index: abs(blocks[index][-1].end - (chapter_start + target)))
        else:
            after = next((index for index in candidates if blocks[index][-1].end > upper), None)
            end = after if after is not None else candidates[-1]
        result.append(blocks[start:end + 1]); start = end + 1
    return result


def relative_blocks(blocks: list[list[TimedWord]], offset: float) -> list[list[TimedWord]]:
    return [[TimedWord(word.text, max(0, word.start - offset), max(0, word.end - offset)) for word in block] for block in blocks]


def update_manifest(entries: list[dict[str, object]], group_id: str) -> None:
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8")) if MANIFEST_PATH.exists() else {"clips": []}
    data["clips"] = [clip for clip in data.get("clips", []) if clip.get("groupId") != group_id] + entries
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=CLIPS_DIR, suffix=".json") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2); handle.write("\n"); temporary = Path(handle.name)
    temporary.replace(MANIFEST_PATH)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fatia um episódio em micro-capítulos naturais.")
    parser.add_argument("--input", required=True, type=Path); parser.add_argument("--title", required=True)
    parser.add_argument("--target-seconds", type=float, default=120); parser.add_argument("--model", default="base.en")
    parser.add_argument("--transcript-file", type=Path); args = parser.parse_args()
    if not args.input.is_file() or args.target_seconds < 30: parser.error("input inválido ou target-seconds menor que 30")
    ensure_ffmpeg(); CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    reference = args.transcript_file.read_text(encoding="utf-8") if args.transcript_file else ""
    duration = probe_duration(args.input)
    size_mb = args.input.stat().st_size / (1024 * 1024)
    log_step(f"[1/5] Recebido vídeo: {args.input.name} ({size_mb:.1f} MB) | Modo: Fatiar Episódio (alvo: {args.target_seconds:g}s)")
    log_step("[2/5] Extraindo áudio com FFmpeg para transcrição...")
    def progress(seconds: float) -> None:
        log_step(f"... transcrito até {int(seconds // 60):02}:{int(seconds % 60):02} / {int(duration // 60):02}:{int(duration % 60):02}")
    log_step(f"[3/5] Transcrevendo com Faster-Whisper (modelo: {args.model}) — progresso a cada ~2 minutos do episódio...")
    words = transcribe(args.input, args.model, initial_prompt=initial_prompt_from_reference(reference) if reference else None, progress_callback=progress)
    corrections = 0
    if reference:
        words, stats = align_words_with_stats(words, reference); corrections = stats.corrections
    blocks = segment_words(words, 18)
    log_step(f"[4/5] Alinhando com Transcript Oficial ({len(words)} palavras alinhadas, {corrections} correções) e montando {len(blocks)} sentenças completas...")
    grouped = chapters(blocks, args.target_seconds); group_id = slugify(args.title); entries = []
    for number, group in enumerate(grouped, start=1):
        content_start, content_end = group[0][0].start, group[-1][-1].end
        next_start = grouped[number][0][0].start if number < len(grouped) else duration
        start = max(0.0, content_start - 0.10)
        end = min(duration, content_end + 0.20, max(content_end, next_start - 0.01))
        stem = f"{group_id}_part{number:02}"
        video, vtt, srt = CLIPS_DIR / f"{stem}.mp4", CLIPS_DIR / f"{stem}.vtt", CLIPS_DIR / f"{stem}.srt"
        log_step(f"[5/5] Recortando micro-capítulos com FFmpeg: Gerando Parte {number:02}/{len(grouped):02} ({int(start // 60):02}:{int(start % 60):02} -> {int(end // 60):02}:{int(end % 60):02}, {len(group)} sentenças)...")
        make_video(args.input.resolve(), video, start, end); write_subtitles(relative_blocks(group, start), vtt, srt)
        entries.append({"id": stem, "groupId": group_id, "groupTitle": args.title, "partNumber": number, "totalParts": len(grouped), "title": f"Parte {number:02} ({int(start // 60):02}:{int(start % 60):02} - {int(end // 60):02}:{int(end % 60):02})", "videoUrl": f"clips/{video.name}", "subtitleUrl": f"clips/{vtt.name}", "duration": round(end - start, 3), "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")})
    update_manifest(entries, group_id); log_step("✅ Importação concluída com sucesso!"); return 0


if __name__ == "__main__":
    bootstrap_venv(); raise SystemExit(main())
