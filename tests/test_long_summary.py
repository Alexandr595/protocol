import io,json,sys,uuid,unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'outputs/local-meeting-ai'))
import meeting_ai as core

class LongSummaryTests(unittest.TestCase):
 def test_all_long_meeting_parts_retained_in_detail(self):
  folder=Path(__file__).parent/'summary-tests'/uuid.uuid4().hex;folder.mkdir(parents=True)
  model=folder/'Qwen3.5-test.gguf';model.write_bytes(b'fake')
  cfg={'llama_exe':str(model.resolve()),'summary_model':str(model.resolve()),'summary_port':18998,'summary_context':8192,'summary_gpu_layers':0}
  details=[];requests=[];payloads=[]
  def urlopen(req,**kw):
   if isinstance(req,str):
    r=io.BytesIO(b'{}');r.status=200;return r
   data=json.loads(req.data)
   if req.full_url.endswith('/tokenize'):return io.BytesIO(json.dumps({'tokens':[1]*100}).encode())
   requests.append(data['max_tokens'])
   payloads.append(data)
   if len(requests)==1:return io.BytesIO(json.dumps({'choices':[{'finish_reason':'length','message':{'content':'TRUNCATED'}}]}).encode())
   text=data['messages'][-1]['content']
   if 'ОСНОВНОЙ ФРАГМЕНТ:' in text:
    note='DETAIL-'+str(len(details)+1);details.append(text)
   else:note='Сводка решений [00:00:00].'
   return io.BytesIO(json.dumps({'choices':[{'finish_reason':'stop','message':{'content':note}}]}).encode())
  proc=MagicMock();proc.poll.return_value=None
  transcript={'segments':[{'start':i*60,'end':i*60+40,'speaker':'Александр' if i%2==0 else 'Игорь','text':'Обсуждаем вопрос номер '+str(i)+'. Предложение пока не принято. '*4} for i in range(180)]}
  with patch.object(core,'config',return_value=cfg),patch.object(core.subprocess,'Popen',return_value=proc),patch.object(core.urllib.request,'urlopen',side_effect=urlopen):
   core.summarize(transcript,folder)
  self.assertGreater(len(details),2)
  self.assertEqual(requests[:2],[1400,2800])
  self.assertEqual(payloads[0]['temperature'],0)
  self.assertEqual(payloads[1]['temperature'],.7)
  self.assertEqual(payloads[1]['presence_penalty'],1.5)
  audits=[p for p in payloads if 'Извлеки подтверждённые факты' in p['messages'][-1]['content']]
  self.assertTrue(audits)
  self.assertTrue(all(p['presence_penalty']==1.5 for p in audits))
  diagnostic=json.loads((folder/'summary-last-incomplete-response.json').read_text(encoding='utf-8'))
  self.assertEqual(diagnostic['content'],'TRUNCATED')
  minutes=(folder/'minutes.md').read_text(encoding='utf-8')
  self.assertNotIn('TRUNCATED',minutes)
  for i in range(len(details)):self.assertIn('DETAIL-'+str(i+1),minutes)
  self.assertIn('179',''.join(details));self.assertIn('[02:59:00',details[-1])
  self.assertEqual(json.loads((folder/'summary-method.json').read_text())['parts'],len(details))
