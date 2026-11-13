import io,json,sys,unittest,zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'outputs/local-meeting-ai'))
from meeting_session import manifest,merge

class SessionTests(unittest.TestCase):
    def archive(self,data,files):
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as z:
            z.writestr('session.json',json.dumps(data))
            for name in files:z.writestr(name,b'audio')
        stream.seek(0);return zipfile.ZipFile(stream)
    def test_closed_session(self):
        data={'status':'stopped','sources':[{'source':'microphone','segments':[{'file':'mic.wav','firstPacketSeconds':0,'audioSeconds':2}]}]}
        with self.archive(data,['mic.wav']) as z:self.assertEqual(manifest(z),data)
    def test_reject_traversal(self):
        data={'status':'stopped','sources':[{'source':'microphone','segments':[{'file':'../mic.wav','firstPacketSeconds':0,'audioSeconds':2}]}]}
        with self.archive(data,['../mic.wav']) as z:
            with self.assertRaises(ValueError):manifest(z)
    def test_reject_recording(self):
        with self.archive({'status':'recording'},[]) as z:
            with self.assertRaises(ValueError):manifest(z)
    def test_reject_no_audio(self):
        with self.archive({'status':'stopped','sources':[]},[]) as z:
            with self.assertRaises(ValueError):manifest(z)
    def data(self,person=None):
        return {'duration':2,'identities':{'0':{'name':'Участник 1','person_id':person}},'segments':[{'start':0,'end':1,'text':'тест','speaker_id':0,'words':[{'start':0,'end':1,'word':'тест'}]}]}
    def test_unknown_people_not_merged_across_sources(self):
        r=merge([('microphone',0,self.data()),('computer',0,self.data())],[])
        self.assertEqual(r['unknown_speakers'],2)
        self.assertNotEqual(r['segments'][0]['speaker_id'],r['segments'][1]['speaker_id'])
    def test_known_person_shared_across_sources(self):
        r=merge([('microphone',0,self.data('person')),('computer',0,self.data('person'))],[])
        self.assertEqual(len(r['identities']),1)
    def test_time_and_warnings_preserved(self):
        data=self.data();r=merge([('computer',10,data)],['microphone missing'])
        self.assertEqual(r['segments'][0]['words'][0]['start'],10)
        self.assertEqual(data['segments'][0]['start'],0)
        self.assertEqual(r['capture_warnings'],['microphone missing'])
if __name__=='__main__':unittest.main()
