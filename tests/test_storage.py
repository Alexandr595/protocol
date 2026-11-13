"""Atomic persistence must keep the old document if publishing fails."""
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'outputs/local-meeting-ai'))
import meeting_ai as core

class StorageTests(unittest.TestCase):
    def test_failed_replace_preserves_original_and_cleans_temp(self):
        folder = Path(__file__).parent / 'storage-tests' / uuid.uuid4().hex
        folder.mkdir(parents=True)
        target = folder / 'settings.json'
        target.write_text('{"value":"old"}', encoding='utf-8')
        with patch.object(Path, 'replace', side_effect=PermissionError('busy')):
            with self.assertRaises(PermissionError):
                core.save(target, {'value': 'new'})
        self.assertEqual(target.read_text('utf-8'), '{"value":"old"}')
        self.assertEqual(list(folder.glob('*.tmp')), [])

if __name__ == '__main__':
    unittest.main()
