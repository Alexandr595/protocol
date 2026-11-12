"""Regression checks without model downloads or access to meeting recordings."""
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import speakers


class SpeakerTests(unittest.TestCase):
    def test_old_vectors_are_rejected_after_model_change(self):
        with patch.object(Path, 'exists', return_value=True), patch.object(
            Path, 'read_text', return_value=json.dumps({'people': [{'embedding': [1, 0]}]})
        ), patch.object(speakers, 'paths',
            return_value=(Path('segmentation'), Path('nemo_en_titanet_large.onnx'))):
            with self.assertRaisesRegex(ValueError, 'другой моделью'):
                speakers.registry()

    def test_close_candidates_remain_unknown(self):
        people = [{'id': 'a', 'embedding': [1, 0]}, {'id': 'b', 'embedding': [.99, .01]}]
        with patch.object(speakers.core, 'config', return_value={}):
            self.assertIsNone(speakers.match_voice(speakers.normalize([1, 0]), people)[0])

    def test_single_profile_does_not_claim_every_voice(self):
        with patch.object(speakers.core, 'config', return_value={}):
            self.assertIsNone(speakers.match_voice(speakers.normalize([0, 1]),
                [{'id': 'a', 'embedding': [1, 0]}])[0])

    def test_overlap_does_not_become_a_named_word(self):
        turns = [{'start': 0, 'end': 2, 'speaker': 0}, {'start': 1, 'end': 3, 'speaker': 1}]
        sid, _, ambiguous = speakers.label_interval(1, 2, turns, {0: 'A', 1: 'B'})
        self.assertIsNone(sid)
        self.assertTrue(ambiguous)

    def test_leading_silence_does_not_split_first_word(self):
        words = [{'start': 0, 'end': 2, 'word': ' На'}, {'start': 2, 'end': 2.5, 'word': ' встрече'}]
        rows = speakers.assign_words([{'words': words}],
            [{'start': 1.5, 'end': 4, 'speaker': 0}], {0: 'A'})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['text'], 'На встрече')
        self.assertEqual(rows[0]['speaker'], 'A')


if __name__ == '__main__':
    unittest.main()
