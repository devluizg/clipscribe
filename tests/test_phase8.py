"""Regression tests for complete-sentence subtitle and chapter boundaries."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from prepare_clip import TimedWord, segment_words
from slice_episode import chapters


def timed_sentence(text: str, start: float = 0.0, step: float = 0.25) -> list[TimedWord]:
    return [TimedWord(word, start + index * step, start + (index + 1) * step) for index, word in enumerate(text.split())]


class SentenceSegmentationTests(unittest.TestCase):
    def test_ten_word_sentence_with_comma_remains_one_segment(self) -> None:
        words = timed_sentence("When I got home last night, the window was smashed.")
        segments = segment_words(words, 18)

        self.assertEqual(len(segments), 1)
        self.assertEqual([word.text for word in segments[0]], [word.text for word in words])

    def test_common_abbreviation_does_not_end_sentence(self) -> None:
        words = timed_sentence("Dr. Holt arrived early and closed the door.")
        self.assertEqual(len(segment_words(words, 18)), 1)

    def test_short_tail_after_pause_is_merged_back(self) -> None:
        words = timed_sentence("This thought continues")
        words += timed_sentence("without any orphan words.", start=2.0)
        self.assertEqual(len(segment_words(words, 18)), 1)


class StrictChapterBoundaryTests(unittest.TestCase):
    def test_chapter_ignores_near_target_block_without_terminal_punctuation(self) -> None:
        blocks = [
            timed_sentence("First sentence.", 0.0, 34.0),
            timed_sentence("still continuing", 75.0, 8.0),
            timed_sentence("Second sentence ends.", 100.0, 5.0),
            timed_sentence("Final sentence.", 145.0, 8.0),
        ]
        grouped = chapters(blocks, 90)

        self.assertEqual(grouped[0][-1][-1].text, "ends.")
        self.assertTrue(grouped[0][-1][-1].text.endswith("."))


if __name__ == "__main__":
    unittest.main()
