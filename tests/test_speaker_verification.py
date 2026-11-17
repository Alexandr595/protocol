import sys,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'outputs/local-meeting-ai'))
from speaker_verification import verify,phrases

class VerificationTests(unittest.TestCase):
 def test_unknown_question_does_not_inherit_cluster_name(self):
  words=[{'start':0,'end':2,'word':' Вопрос?'},{'start':2,'end':4,'word':' Ответ.'}]
  row={'start':0,'end':4,'text':'Вопрос? Ответ.','speaker_id':0,'speaker':'Known','words':words}
  vectors=iter([np.array([0.,1.]),np.array([1.,0.])])
  result=verify([row],np.zeros(64000),None,{0:np.array([1.,0.])},lambda *_:next(vectors))
  self.assertIsNone(result[0]['speaker_id']);self.assertEqual(result[1]['speaker'],'Known')
  self.assertEqual(row['speaker_id'],0)
 def test_hesitation_does_not_split_short_sample(self):
  words=[{'start':0,'end':1,'word':' по поводу...'},{'start':1,'end':3,'word':' лицензии.'}]
  self.assertEqual(len(list(phrases(words))),1)
 def test_insufficient_audio_is_not_confirmed(self):
  row={'speaker_id':0,'speaker':'Known','words':[{'start':0,'end':.2,'word':' Да'}]}
  result=verify([row],np.zeros(3200),None,{0:np.array([1.,0.])},lambda *_:self.fail('Too short'))
  self.assertIsNone(result[0]['speaker_id'])
