"""Unit tests for official-transcript alignment and natural episode slicing."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from align_transcript import align_words
from prepare_clip import TimedWord
from slice_episode import chapters


class AlignmentTests(unittest.TestCase):
    def test_small_whisper_replacement_uses_official_spelling_and_audio_window(self) -> None:
        # Whisper heard both a proper name and a compound word incorrectly.
        whisper = [
            TimedWord("Lavern", 0.00, 0.30),
            TimedWord("bird", 0.30, 0.56),
            TimedWord("gold", 0.56, 0.90),
        ]
        aligned = align_words(whisper, "Laverne burgled.")

        self.assertEqual([word.text for word in aligned], ["Laverne", "burgled."])
        self.assertEqual(aligned[0].start, 0.00)
        self.assertEqual(aligned[-1].end, 0.90)
        self.assertGreaterEqual(aligned[1].start, aligned[0].end)


class ChapterTests(unittest.TestCase):
    def test_chapters_cut_only_on_subtitle_boundaries_near_target(self) -> None:
        blocks = [
            [TimedWord(f"Sentence{index}.", start, start + 27)]
            for index, start in enumerate(range(0, 180, 30), start=1)
        ]
        result = chapters(blocks, 120)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0][-1][-1].end, 117)
        self.assertEqual(result[1][0][0].start, 120)
        self.assertEqual(sum(len(chapter) for chapter in result), len(blocks))


if __name__ == "__main__":
    unittest.main()
