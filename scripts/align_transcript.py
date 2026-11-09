"""Lexically align official transcript words with Whisper word timestamps."""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Iterable

from prepare_clip import TimedWord

WORD = re.compile(r"(?:[A-Za-z]\.){2,}|[A-Za-z0-9]+(?:['’][A-Za-z0-9]+)?(?:[.!?,;:]|…)?")


@dataclass(frozen=True)
class ReferenceWord:
    text: str
    norm: str


@dataclass(frozen=True)
class AlignmentStats:
    aligned_words: int
    corrections: int


def normalize(word: str) -> str:
    return "".join(re.findall(r"[a-z0-9]", word.lower()))


def clean_reference_text(text: str) -> str:
    lines = []
    for line in text.replace("\r", "").split("\n"):
        line = re.sub(r"\[[^\]]*\]", " ", line)
        if re.search(r"subslikescript|transcript|copyright", line, re.I):
            continue
        line = re.sub(r"^\s*[A-Z][A-Z .'-]{1,35}:\s*", "", line)
        line = re.sub(r"^\s*-\s*", "", line)
        lines.append(line)
    return " ".join(lines)


def reference_words(text: str) -> list[ReferenceWord]:
    return [ReferenceWord(match.group(0), normalize(match.group(0))) for match in WORD.finditer(clean_reference_text(text)) if normalize(match.group(0))]


def initial_prompt_from_reference(text: str, limit: int = 180) -> str:
    """Give Whisper uncommon official vocabulary without feeding it the whole script."""
    seen: set[str] = set(); selected = []
    for item in reference_words(text):
        if len(item.norm) >= 5 and item.norm not in seen:
            seen.add(item.norm); selected.append(item.text.rstrip(".!?,;:"))
        if len(selected) >= limit:
            break
    return ", ".join(selected)


def interpolate(reference: list[ReferenceWord], window: list[TimedWord]) -> list[TimedWord]:
    if not reference or not window:
        return window
    start, end = window[0].start, window[-1].end
    span = max(end - start, 0.001)
    result = []
    for index, item in enumerate(reference):
        word_start = start + span * index / len(reference)
        word_end = start + span * (index + 1) / len(reference)
        result.append(TimedWord(item.text, word_start, word_end))
    return result


def align_words_with_stats(whisper_words: Iterable[TimedWord], official_text: str) -> tuple[list[TimedWord], AlignmentStats]:
    """Preserve acoustic timestamps and report official-text corrections."""
    whisper = list(whisper_words); official = reference_words(official_text)
    matcher = difflib.SequenceMatcher(None, [normalize(word.text) for word in whisper], [word.norm for word in official], autojunk=False)
    aligned: list[TimedWord] = []; corrections = 0
    for tag, left_a, left_b, right_a, right_b in matcher.get_opcodes():
        acoustic, reference = whisper[left_a:left_b], official[right_a:right_b]
        if tag == "equal":
            aligned.extend(TimedWord(ref.text, timed.start, timed.end) for timed, ref in zip(acoustic, reference))
        elif tag == "replace" and acoustic and reference and max(len(acoustic), len(reference)) <= 4:
            aligned.extend(interpolate(reference, acoustic))
            corrections += max(len(acoustic), len(reference))
        elif tag in {"replace", "delete"}:
            aligned.extend(acoustic)
        # Inserts have no trustworthy audio timing and are intentionally ignored.
    return aligned, AlignmentStats(len(aligned), corrections)


def align_words(whisper_words: Iterable[TimedWord], official_text: str) -> list[TimedWord]:
    """Backward-compatible alignment API used by existing callers and tests."""
    return align_words_with_stats(whisper_words, official_text)[0]
