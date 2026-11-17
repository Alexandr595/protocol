"""Verify local phrases instead of inheriting a name from a whole-meeting cluster."""
import copy
import numpy as np


def phrases(words):
    part=[]
    for word in words:
        if part and (word['start']-part[-1]['end']>=0.5 or word['end']-part[0]['start']>8):
            yield part;part=[]
        part.append(word)
        if word['word'].rstrip().endswith(('?', '!', '.')) and not word['word'].rstrip().endswith('...'):
            yield part;part=[]
    if part:yield part


def verify(rows, audio, extractor, references, embed, threshold=0.60, margin=0.10):
    output=[]
    for row in rows:
        if row.get('speaker_id') not in references or not row.get('words'):
            output.append(row);continue
        for words in phrases(row['words']):
            item=copy.deepcopy(row)
            item.update(start=words[0]['start'],end=words[-1]['end'],words=words,
                        text=''.join(w['word'] for w in words).strip())
            vector=None
            if item['end']-item['start']>=1.2:
                vector=embed(extractor,audio[int(item['start']*16000):int(item['end']*16000)])
            scores={sid:float(np.dot(vector,ref)) for sid,ref in references.items()} if vector is not None else {}
            score=scores.get(row['speaker_id'],-1)
            other=max((v for sid,v in scores.items() if sid!=row['speaker_id']),default=-1)
            confirmed=score>=threshold and score-other>=margin
            item['identity_verification']={'confirmed':confirmed,'similarity':score if scores else None}
            if not confirmed:
                item.update(speaker_id=None,speaker='Говорящий не определён',ambiguous=False)
            output.append(item)
    return output
