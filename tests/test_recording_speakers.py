import sys,json,time,wave,uuid,unittest,threading
from pathlib import Path
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'outputs/local-meeting-ai'))
import meeting_ai as core
import recording,speakers

class CaptureTests(unittest.TestCase):
 def setUp(self):
  self.root=Path(__file__).parent/'capture-tests'/uuid.uuid4().hex;self.root.mkdir(parents=True)
  self.override=patch.object(core,'ROOT',self.root);self.override.start();core.database().close()
 def tearDown(self):self.override.stop()
 def test_missing_microphone(self):
  with patch('recording.WindowsAudio') as backend:
   backend.return_value.devices.return_value=[]
   with self.assertRaisesRegex(ValueError,'Микрофон'):recording.Recorder().start()
 def test_capture_wav_and_queue(self):
  class Stream:
   def __init__(self,callback):self.callback=callback
   def start_stream(self):self.callback(bytes(32000*2),32000,{},0)
   def is_active(self):return True
   def stop_stream(self):pass
   def close(self):pass
  device={'id':1,'kind':'mic','rate':16000,'channels':1,'name':'test'}
  with patch('recording.WindowsAudio') as backend:
   backend.return_value.devices.return_value=[device]
   backend.return_value.open.side_effect=lambda d,cb:Stream(cb)
   rec=recording.Recorder();rec.start(device=1,name='Проверка');rec.origin-=2;rec.stop();rec.thread.join(5)
   self.assertEqual(rec.status,'complete',rec.error)
   with wave.open(str(rec.path)) as audio:self.assertGreaterEqual(audio.getnframes(),32000)
   with core.database() as db:self.assertEqual(db.execute('SELECT status FROM jobs').fetchone()[0],'queued')
 def test_refresh_does_not_stop_live_capture(self):
  rec=recording.Recorder();rec.thread=threading.current_thread()
  with patch('recording.WindowsAudio') as backend:
   rec.devices();backend.assert_not_called()
 def test_failed_open_creates_no_empty_session(self):
  device={'id':1,'kind':'mic','rate':16000,'channels':1,'name':'headset'}
  with patch('recording.WindowsAudio') as backend:
   backend.return_value.devices.return_value=[device]
   backend.return_value.open.side_effect=OSError(-9996,'Invalid device')
   rec=recording.Recorder()
   with self.assertRaisesRegex(RuntimeError,'headset'):rec.start(device=1)
   rec.thread.join(2)
   self.assertEqual(rec.recoverable(),[])
   self.assertEqual(list(self.root.glob('recordings/*/session.json')),[])
   self.assertEqual(rec.reset()['status'],'idle')
 def test_capture_resolves_changed_device_index(self):
  device={'id':1,'kind':'mic','rate':16000,'channels':1,'name':'headset'}
  with patch('recording.WindowsAudio') as backend:
   backend.return_value.devices.side_effect=[[device.copy()],[dict(device,id=7)]]
   backend.return_value.open.side_effect=OSError(-9996,'Invalid device')
   rec=recording.Recorder()
   with self.assertRaises(RuntimeError):rec.start(device=1)
   rec.thread.join(2)
   self.assertEqual(backend.return_value.open.call_args.args[0]['id'],7)
 def test_reset_cannot_interrupt_capture(self):
  rec=recording.Recorder();rec.thread=threading.current_thread()
  with self.assertRaises(ValueError):rec.reset()
 def test_dismiss_keeps_audio_and_persists(self):
  folder=self.root/'recordings'/'failed';folder.mkdir(parents=True)
  core.save(folder/'session.json',{'purpose':'meeting','status':'error','name':'test','duration':3})
  audio=folder/'mic.pcm';audio.write_bytes(b'keep audio')
  rec=recording.Recorder();self.assertTrue(rec.recoverable()[0]['can_recover'])
  with self.assertRaises(ValueError):rec.dismiss('../failed')
  rec.dismiss('failed');self.assertEqual(recording.Recorder().recoverable(),[])
  self.assertEqual(audio.read_bytes(),b'keep audio')
 def test_empty_attempt_cannot_be_recovered(self):
  folder=self.root/'recordings'/'empty';folder.mkdir(parents=True)
  core.save(folder/'session.json',{'purpose':'meeting','status':'error','name':'test','duration':0})
  rec=recording.Recorder();self.assertFalse(rec.recoverable()[0]['can_recover'])
  with self.assertRaises(ValueError):rec.recover('empty')
  rec.dismiss('empty');self.assertEqual(rec.recoverable(),[])
 def test_overlapping_words_unassigned(self):
  turns=[{'speaker':0,'start':0,'end':3},{'speaker':1,'start':1,'end':4}]
  sid,name,ambiguous=speakers.label_interval(1.5,2,turns,{0:'Иван',1:'Мария'})
  self.assertIsNone(sid);self.assertTrue(ambiguous)
  self.assertEqual(speakers.clean_intervals(turns,0),[(0,1)])
 def test_unknown_and_ambiguous_identities(self):
  people=[{'name':'Иван','embedding':[1,0]},{'name':'Пётр','embedding':[0,1]}]
  self.assertIsNone(speakers.match_voice(np.array([-1,0]),people)[0])
  self.assertIsNone(speakers.match_voice(speakers.normalize([1,1]),people)[0])
  self.assertEqual(speakers.match_voice(np.array([1,0]),people)[0]['name'],'Иван')
 def test_named_transcript(self):
  self.assertIn('[Иван]',core.transcript_lines({'segments':[{'start':0,'end':1,'text':'Привет','speaker':'Иван'}]})[0])

if __name__=='__main__':unittest.main()
