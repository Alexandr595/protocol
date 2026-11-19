import sys,unittest,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'outputs/local-meeting-ai'))
from accounts import Accounts
from speaker_groups import reconcile,corroborated_name
class AccountTests(unittest.TestCase):
 def test_users_sessions_revocation(self):
  p=Path(__file__).parent/'accounts-tests'/uuid.uuid4().hex;p.mkdir(parents=True)
  a=Accounts(p,{'username':'owner','password':'test-password-123'})
  token=a.login('owner','test-password-123','client');cookie='protocol_session='+token
  self.assertEqual(a.user(cookie)['role'],'admin');a.create('staff','staff-password')
  self.assertEqual(a.user('protocol_session='+a.login('staff','staff-password','client'))['role'],'user')
  with self.assertRaises(ValueError):a.login('owner','wrong','client')
  with self.assertRaises(ValueError):a.create('staff','staff-password')
  a.logout(cookie);self.assertIsNone(a.user(cookie))
  self.assertNotIn(b'test-password-123',a.path.read_bytes())
 def test_no_public_admin_creation(self):
  import inspect
  self.assertEqual(list(inspect.signature(Accounts.create).parameters),['self','login','password'])
class GroupTests(unittest.TestCase):
 def entry(self,key,vec,start,end,seconds=10):return {'key':key,'vector':vec,'intervals':[(start,end)],'seconds':seconds}
 def test_reconcile_windows_and_ignore_tiny_fragments(self):
  groups=reconcile([self.entry(0,[1,0],0,10),self.entry(1,[0,1],11,21),self.entry(2,[1,.05],30,40),self.entry(3,[0,1],45,46,1)])
  self.assertEqual([[x['key'] for x in g] for g in groups],[[0,2],[1]])
 def test_concurrent_speech_not_merged(self):
  self.assertEqual(len(reconcile([self.entry(0,[1,0],0,10),self.entry(1,[1,.05],2,8)])),2)
 def test_short_boundary_overlap_allowed(self):
  self.assertEqual(len(reconcile([self.entry(0,[1,0],0,20),self.entry(1,[1,.05],19.8,40)])),1)
 def test_single_sample_cannot_relax_identity(self):
  people=[{'id':'a','embedding':[1,0]},{'id':'b','embedding':[0,1]}]
  self.assertIsNone(corroborated_name([self.entry(0,[1,0],0,10)],people))
  self.assertEqual(corroborated_name([self.entry(0,[1,0],0,10),self.entry(1,[1,0],20,30)],people)['id'],'a')
import json,threading,urllib.request,urllib.error
from http.server import ThreadingHTTPServer
from unittest.mock import patch
class AuthorizationTests(unittest.TestCase):
 def test_staff_cannot_list_or_create_users(self):
  import web_server
  p=Path(__file__).parent/'accounts-tests'/uuid.uuid4().hex;p.mkdir(parents=True)
  a=Accounts(p,{'username':'owner','password':'test-password-123'});a.create('staff','staff-password')
  token=a.login('staff','staff-password','test')
  with patch.object(web_server,'accounts',a),patch.object(web_server.network,'authorized',return_value=False),patch.object(web_server.network,'valid_host',return_value=True):
   server=ThreadingHTTPServer(('127.0.0.1',0),web_server.Handler)
   thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
   try:
    for data in (None,b'{"login":"intruder","password":"password123"}'):
     req=urllib.request.Request(f'http://127.0.0.1:{server.server_port}/api/admin/users',data=data,headers={'Cookie':'protocol_session='+token,'X-Local-App':'meeting-ai'})
     with self.assertRaises(urllib.error.HTTPError) as e:urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req)
     self.assertEqual(e.exception.code,403)
    self.assertEqual(len(a.users()),2)
   finally:server.shutdown();server.server_close();thread.join()
class SummaryFallbackTests(unittest.TestCase):
 def test_nonshrinking_summary_keeps_every_fragment(self):
  import meeting_ai as core,summary_pipeline
  p=Path(__file__).parent/'accounts-tests'/uuid.uuid4().hex;p.mkdir(parents=True)
  model=p/'model';model.write_bytes(b'test')
  cfg={'summary_context':8192,'summary_model':str(model)}
  def ask(text,**options):
   return text if options.get('merge') else 'source-evidence '+text
  rows={'segments':[{'start':i,'end':i+1,'text':('unique'+str(i)+' ')*90} for i in range(20)]}
  summary_pipeline.run(rows,p,cfg,ask,core.chunks,core.transcript_lines,core.save,model)
  result=(p/'summary.md').read_text(encoding='utf-8')
  self.assertIn('Единое объединение не удалось',result)
  for i in range(20):self.assertIn('unique'+str(i)+' ',result)
  self.assertTrue((p/'summary-method.json').exists())

if __name__=='__main__':unittest.main()
