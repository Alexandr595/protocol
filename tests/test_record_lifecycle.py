import sys,uuid,unittest,json
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'outputs/local-meeting-ai'))
import meeting_ai as core
from record_lifecycle import change

class LifecycleTests(unittest.TestCase):
 def setUp(self):
  self.root=Path(__file__).parent/'lifecycle-tests'/uuid.uuid4().hex;self.root.mkdir(parents=True)
  self.override=patch.object(core,'ROOT',self.root);self.override.start()
  self.source=self.root/'test.wav';self.source.write_bytes(b'original audio');self.key=core.add(self.source)
 def tearDown(self):self.override.stop()
 def test_trash_preserves_files_and_restore_is_held(self):
  change(self.key,'trash')
  with core.database() as db:
   self.assertIsNone(core.claim_next(db));row=db.execute('SELECT * FROM jobs').fetchone()
   self.assertEqual(row['status'],'deleted');self.assertEqual(Path(row['path']).read_bytes(),b'original audio')
  self.assertTrue(list((self.root/'state/trash-backups'/self.key).glob('*.json')))
  change(self.key,'restore')
  with core.database() as db:self.assertEqual(db.execute('SELECT status FROM jobs').fetchone()[0],'held')
 def test_running_cannot_be_trashed(self):
  with core.database() as db:core.claim_next(db)
  with self.assertRaises(ValueError):change(self.key,'trash')
 def test_regeneration_archives_previous_results(self):
  with core.database() as db:db.execute("UPDATE jobs SET status='done'")
  folder=self.root/'results'/self.key[:16];folder.mkdir()
  core.save(folder/'transcript.json',{'segments':[]})
  (folder/'summary.md').write_text('old brief');(folder/'minutes.md').write_text('old detail')
  change(self.key,'summarize')
  archive=next(folder.glob('previous-summary-*'))
  self.assertEqual((archive/'minutes.md').read_text(),'old detail')
  self.assertFalse((folder/'summary.md').exists())
  with core.database() as db:self.assertEqual(db.execute('SELECT status FROM jobs').fetchone()[0],'queued')
