from test_record_lifecycle import LifecycleTests
from record_lifecycle import purge, purge_expired, RETENTION_SECONDS
import meeting_ai as core
from pathlib import Path
from unittest.mock import patch

class PurgeTests(LifecycleTests):
 def test_expiry_preserves_source_and_recent_trash(self):
  from record_lifecycle import change
  change(self.key,'trash')
  with core.database() as db:
   db.execute('UPDATE jobs SET deleted_at=100')
   audio=Path(db.execute('SELECT path FROM jobs').fetchone()[0])
  purge_expired(now=100+RETENTION_SECONDS-1)
  self.assertTrue(audio.exists())
  purge_expired(now=100+RETENTION_SECONDS)
  self.assertFalse(audio.exists());self.assertTrue(self.source.exists())
  with core.database() as db:self.assertEqual(db.execute('SELECT count(*) FROM jobs').fetchone()[0],0)
 def test_active_cannot_be_purged(self):
  with self.assertRaises(ValueError):purge(self.key)
  self.assertTrue(self.source.exists())
 def test_external_path_is_rejected(self):
  from record_lifecycle import change
  change(self.key,'trash')
  with core.database() as db:db.execute('UPDATE jobs SET path=?',(str(self.source),))
  with self.assertRaises(ValueError):purge(self.key)
  self.assertTrue(self.source.exists())
 def test_failed_delete_cannot_be_restored_and_can_retry(self):
  from record_lifecycle import change
  change(self.key,'trash')
  with patch.object(Path,'unlink',side_effect=PermissionError('busy')):
   with self.assertRaises(PermissionError):purge(self.key)
  with self.assertRaises(ValueError):change(self.key,'restore')
  self.assertTrue(purge(self.key))
