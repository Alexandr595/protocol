import sys
from pathlib import Path
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'outputs/local-meeting-ai'))
import meeting_ai as core
from folder_watch import FolderWatcher


class FolderTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(__file__).parent/'folder-tests'/uuid.uuid4().hex
        self.root.mkdir(parents=True)
        self.patch=patch.object(core,'ROOT',self.root)
        self.patch.start()
        core.database().close()
        self.watcher=FolderWatcher(self.root)
        self.file=self.root/'incoming/meeting.wav'

    def tearDown(self):
        self.patch.stop()

    def count(self):
        with core.database() as db:
            return db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0]

    def test_stable_then_import_and_no_rehash_after_restart(self):
        self.file.write_bytes(b'first audio')
        self.watcher.scan(now=0)
        self.watcher.scan(now=59)
        self.assertEqual(self.count(),0)
        self.watcher.scan(now=61)
        self.assertEqual(self.count(),1)
        restarted=FolderWatcher(self.root)
        with patch.object(core,'add') as add:
            restarted.scan(now=100)
            add.assert_not_called()

    def test_changed_file_restarts_stability_timer(self):
        self.file.write_bytes(b'a')
        self.watcher.scan(now=0)
        self.file.write_bytes(b'new audio')
        self.watcher.scan(now=59)
        self.watcher.scan(now=61)
        self.assertEqual(self.count(),0)
        self.watcher.scan(now=120)
        self.assertEqual(self.count(),1)

    def test_open_writer_is_skipped(self):
        with self.file.open('wb') as stream:
            stream.write(b'audio');stream.flush()
            self.watcher.scan(now=0)
            self.watcher.scan(now=61)
            self.assertEqual(self.count(),0)
            self.assertIn('занят',self.watcher.pending[0]['reason'])
        self.watcher.scan(now=62)
        self.assertEqual(self.count(),1)

    def test_marker_mode(self):
        self.watcher.configure({'mode':'ready'})
        self.file.write_bytes(b'audio')
        self.watcher.scan(now=0);self.watcher.scan(now=100)
        self.assertEqual(self.count(),0)
        Path(str(self.file)+'.ready').touch()
        self.watcher.scan(now=101)
        self.assertEqual(self.count(),1)

    def test_priority_hold_and_atomic_claim(self):
        ids=[]
        for n in range(3):
            path=self.root/f'{n}.wav';path.write_bytes(bytes([n+1]))
            ids.append(core.add(path))
        with core.database() as db:
            db.execute('UPDATE jobs SET priority=20 WHERE id=?',(ids[2],))
            db.execute("UPDATE jobs SET status='held',priority=20 WHERE id=?",(ids[1],))
        with core.database() as db:
            self.assertEqual(core.claim_next(db)['id'],ids[2])
            self.assertEqual(core.claim_next(db)['id'],ids[0])
            self.assertIsNone(core.claim_next(db))

    def test_pause_persists_and_scan_works_while_paused(self):
        self.watcher.configure({'processing_enabled':False})
        self.assertFalse(FolderWatcher(self.root).settings['processing_enabled'])
        self.file.write_bytes(b'audio')
        self.watcher.scan(now=0);self.watcher.scan(now=61)
        self.assertEqual(self.count(),1)

if __name__=='__main__':
    unittest.main()
