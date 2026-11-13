import json, struct, sys, unittest, uuid, threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'outputs/local-meeting-ai'))
import meeting_ai as core
import recording, session_audio, long_audio, summary_pipeline, speakers
from audio_io import decoded_audio

class LongRecordingTests(unittest.TestCase):
 def setUp(self):
  self.folder=Path(__file__).parent/'long-recording-tests'/uuid.uuid4().hex
  self.folder.mkdir(parents=True)

 def test_rf64_sizes_and_real_decoder(self):
  count=16000*40*3600
  header=session_audio.wav_header(count)
  self.assertEqual(header[:4],b'RF64')
  self.assertEqual(struct.unpack_from('<QQQ',header,20),(count*2+72,count*2,count))
  self.assertEqual(len(header),80)
  path=self.folder/'small-rf64.wav'
  with patch.object(session_audio,'RIFF_MAX',0):
   session_audio.write_wav(path,[np.full(16000,1000,dtype='<i2')],16000)
  self.assertEqual(path.read_bytes()[:4],b'RF64')
  with decoded_audio(path,self.folder) as audio:
   self.assertEqual(len(audio),16000)
   self.assertAlmostEqual(float(audio[8000]),1000/32768,places=5)

 def test_recording_does_not_stop_at_forty_hours(self):
  rec=recording.Recorder();rec.origin=0;rec.purpose='meeting'
  rec.stop_event=threading.Event()
  rec.metadata={'tracks':[{'kind':'mic','rate':16000,'channels':1}]}
  rec.track_frames={'mic':0};rec.status='recording'
  observed=[]
  def active():
   observed.append(rec.stop_event.is_set())
   if len(observed)==2:rec.stop_event.set()
   return True
  stream=MagicMock(error='',warning='');stream.is_active.side_effect=active
  rec.chunks=MagicMock();rec.chunks.get.return_value=('mic',b'\x00\x00',0,1);rec.chunks.empty.return_value=True
  with patch.object(recording.time,'perf_counter',return_value=40*3600),patch.object(recording,'assemble',return_value=self.folder/'meeting.wav'),patch.object(rec,'_publish',return_value={'test':True}):
   rec._write(MagicMock(),[stream],self.folder)
  self.assertEqual(observed,[False,False]);self.assertEqual(rec.status,'complete',rec.error)
  self.assertEqual(rec.duration,40*3600)

 def test_asr_windows_overlap_and_resume(self):
  source=self.folder/'audio.wav';source.write_bytes(b'fixture')
  audio=np.zeros(9*16000,dtype=np.float32)
  calls=[]
  def transcribe(samples,**kw):
   calls.append((len(samples),kw))
   # Speech in global seconds 3.5 and 4.5 is visible in both overlapping windows.
   offset=0 if len(calls)==1 else 3 if len(calls)==2 else 7
   words=[SimpleNamespace(start=t-offset-.2,end=t-offset+.2,word=' слово'+str(t))
      for t in (1.,3.5,4.5,7.5,8.5) if offset<=t<offset+len(samples)/16000]
   return iter([SimpleNamespace(words=words,start=0,end=len(samples)/16000,text='')]),None
  model=MagicMock();model.transcribe.side_effect=transcribe
  with patch.object(long_audio,'WINDOW',4),patch.object(long_audio,'OVERLAP',1),patch.object(long_audio,'speech_regions',side_effect=lambda x:[{'start':0,'end':len(x)}]):
   rows=long_audio.transcribe(model,audio,self.folder,source,{},core.save)
   again=long_audio.transcribe(model,audio,self.folder,source,{},core.save)
  self.assertEqual(rows,again);self.assertEqual(len(calls),3)
  text=' '.join(r['text'] for r in rows)
  for t in (1.,3.5,4.5,7.5,8.5):self.assertEqual(text.count('слово'+str(t)),1)
  self.assertFalse(calls[1][1]['condition_on_previous_text'])
  self.assertLessEqual(max(c[0] for c in calls),6*16000)

 def test_audit_and_resume_after_interruption(self):
  model=self.folder/'model';model.write_bytes(b'model')
  cfg={'summary_context':8192,'summary_model':str(model)}
  data={'segments':[{'start':i*900,'end':i*900+10,'speaker':'Игорь',
       'text':('Срок пятница. ' if i<19 else 'Отменяем пятницу, срок понедельник. ')+'Обсуждение. '*200} for i in range(20)]}
  calls=[];fail=[True]
  def ask(text,**options):
   calls.append((text,options))
   if options.get('audit'):
    if fail[0]:fail[0]=False;raise RuntimeError('simulated interruption')
    return 'Исправление: срок понедельник [04:45:00].' if 'Отменяем пятницу' in text else 'Исправлений нет.'
   if options.get('merge'):
    return 'Срок понедельник [04:45:00].' if 'Исправление:' in text or 'Срок понедельник' in text else 'Срок пятница.'
   return 'Обсуждали срок пятница.'
  args=(data,self.folder,cfg,ask,core.chunks,core.transcript_lines,core.save,model)
  with self.assertRaisesRegex(RuntimeError,'simulated'):summary_pipeline.run(*args)
  self.assertFalse((self.folder/'summary.md').exists())
  first_calls=len(calls)
  summary_pipeline.run(*args)
  self.assertTrue(all(o.get('audit') or o.get('merge') for _,o in calls[first_calls:]))
  method=json.loads((self.folder/'summary-method.json').read_text())
  self.assertEqual(method['parts'],method['audited_parts'])
  self.assertIn('понедельник',(self.folder/'summary.md').read_text(encoding='utf-8'))
  audit='\n'.join(t for t,o in calls[first_calls:] if o.get('audit'))
  audit_inputs=[t for t,o in calls[first_calls:] if o.get('audit')]
  self.assertNotIn('ПРОВЕРЯЕМАЯ СВОДКА',audit)
  self.assertNotIn('Отменяем пятницу',audit_inputs[0])
  self.assertIn('Отменяем пятницу',audit_inputs[-1])
  for i in range(20):self.assertIn(core.stamp(i*900),audit)
  count=len(calls);summary_pipeline.run(*args);self.assertEqual(len(calls),count)
  data['segments'][-1]['text']='Изменённый исходник.'
  summary_pipeline.run(*args);self.assertGreater(len(calls),count)

 def test_repeated_utterances_and_early_first_word_are_retained(self):
  source=self.folder/'speech.wav';source.write_bytes(b'fixture')
  audio=np.zeros(12*16000,dtype=np.float32)
  model=MagicMock()
  def transcribe(samples,**options):
   # Whisper may timestamp the first word before the VAD speech start.
   return iter([SimpleNamespace(start=0,end=2,text='Повтор',
       words=[SimpleNamespace(start=0,end=.5,word=' Повтор')])]),None
  model.transcribe.side_effect=transcribe
  with patch.object(long_audio,'speech_regions',return_value=[{'start':16000,'end':32000},{'start':160000,'end':176000}]):
   rows=long_audio.transcribe(model,audio,self.folder,source,{},core.save)
  self.assertEqual([r['text'] for r in rows],['Повтор','Повтор'])
  self.assertEqual([r['start'] for r in rows],[0,9])
  self.assertEqual(model.transcribe.call_count,2)

 def test_context_retrieval_uses_earlier_quotes_not_future(self):
  parts=['[00:00:00] Александр: Пилот записи запускаем в пятницу.',
     '[01:00:00] Мария: Обсуждаем питание сотрудников.',
     '[02:00:00] Игорь: Пилот записи переносим на понедельник.',
     '[03:00:00] Александр: Пилот записи снова изменился.']
  earlier=summary_pipeline.EarlierContext(parts)
  found=earlier.get(2,parts[2],parts[1])
  self.assertIn('пятницу',found);self.assertNotIn('03:00:00',found)

 def test_long_monologue_keeps_name_on_every_fragment(self):
  words=[{'start':i,'end':i+.8,'word':' слово'+str(i)} for i in range(800)]
  data={'segments':[{'start':0,'end':800,'speaker':'Александр','text':''.join(w['word'] for w in words).strip(),'words':words}]}
  lines=core.transcript_lines(data)
  self.assertGreater(len(lines),3)
  self.assertTrue(all('[Александр]' in line for line in lines))
  self.assertIn('слово799',lines[-1]);self.assertNotIn('[00:00:00',lines[-1])
  data['segments'][0].pop('words')
  self.assertTrue(all('[Александр]' in line for line in core.transcript_lines(data)))

 def test_window_local_speaker_ids_do_not_conflate_people(self):
  source=self.folder/'audio.wav';source.write_bytes(b'fixture')
  transcript=self.folder/'transcript.json'
  core.save(transcript,{'segments':[{'start':1,'end':2,'text':'Один'},{'start':6,'end':7,'text':'Другой'}]})
  diarizer=MagicMock()
  diarizer.process.return_value.sort_by_start_time.return_value=[SimpleNamespace(start=0,end=5,speaker=0)]
  with patch.object(speakers,'engines',return_value=(diarizer,MagicMock())),patch.object(speakers,'registry',return_value={'people':[]}),patch.object(speakers,'decoded_audio') as decoded,patch.object(speakers,'voice_vector',side_effect=[(np.array([1.,0.]),4),(np.array([0.,1.]),4)]),patch.object(long_audio,'WINDOW',5),patch.object(long_audio,'OVERLAP',0):
   decoded.return_value.__enter__.return_value=np.zeros(10*16000,dtype=np.float32)
   speakers.diarize(source,transcript)
  result=json.loads(transcript.read_text(encoding='utf-8'))
  self.assertNotEqual(result['segments'][0]['speaker'],result['segments'][1]['speaker'])
  self.assertEqual(result['speaker_turns'][1]['start'],5)

if __name__=='__main__':unittest.main()
