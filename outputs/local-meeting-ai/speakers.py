"""Offline diarization, local voice enrollment and conservative identity matching."""
import json
from pathlib import Path
import sys
import uuid
import bisect
import numpy as np
import meeting_ai as core
from audio_io import decoded_audio


def paths():
    cfg=core.config()
    return core.resolve(cfg['speaker_segmentation']),core.resolve(cfg['speaker_embedding'])


def available():
    try:return all(p.is_file() for p in paths())
    except KeyError:return False


def registry():
    path=core.ROOT/'voices/profiles.json'
    bank=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'version':2,'people':[]}
    expected=paths()[1].name
    actual=bank.get('embedding_model','wespeaker_en_voxceleb_resnet34_LM.onnx')
    if bank['people'] and actual!=expected:
        raise ValueError('Профили голосов созданы другой моделью. Перенесите профили перед распознаванием.')
    return bank


def public_profiles():
    return [{k:p[k] for k in ('id','name','samples','speech_seconds')} for p in registry()['people']]


def engines():
    import sherpa_onnx as s
    segmentation,embedding=paths()
    cfg=s.OfflineSpeakerDiarizationConfig(
        segmentation=s.OfflineSpeakerSegmentationModelConfig(
            pyannote=s.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(segmentation)),num_threads=4,provider='cpu'),
        embedding=s.SpeakerEmbeddingExtractorConfig(model=str(embedding),num_threads=4,provider='cpu'),
        clustering=s.FastClusteringConfig(num_clusters=-1,threshold=core.config().get('speaker_cluster_threshold',0.5)),
        min_duration_on=0.3,min_duration_off=0.5)
    if not cfg.validate():raise RuntimeError('Не найдены модели голосов.')
    diarizer=s.OfflineSpeakerDiarization(cfg)
    extractor=s.SpeakerEmbeddingExtractor(s.SpeakerEmbeddingExtractorConfig(model=str(embedding),num_threads=4,provider='cpu'))
    return diarizer,extractor


def normalize(vector):
    vector=np.asarray(vector,dtype=np.float32)
    norm=float(np.linalg.norm(vector))
    if not np.isfinite(norm) or norm<1e-8:raise ValueError('Не удалось выделить голос.')
    return vector/norm


def embed(extractor,audio):
    stream=extractor.create_stream()
    stream.accept_waveform(sample_rate=16000,waveform=np.ascontiguousarray(audio))
    stream.input_finished()
    if not extractor.is_ready(stream):return None
    return normalize(extractor.compute(stream))


def clean_intervals(turns, speaker):
    """Subtract other speakers: overlapping audio must not enter an identity sample."""
    parts=[]
    for turn in turns:
        if turn['speaker']!=speaker:continue
        pieces=[(turn['start'],turn['end'])]
        for other in turns:
            if other['speaker']==speaker:continue
            next_pieces=[]
            for a,b in pieces:
                if other['end']<=a or other['start']>=b:next_pieces.append((a,b))
                else:
                    if a<other['start']:next_pieces.append((a,other['start']))
                    if other['end']<b:next_pieces.append((other['end'],b))
            pieces=next_pieces
        parts.extend((a,b) for a,b in pieces if b-a>=1.0)
    return sorted(parts,key=lambda x:x[1]-x[0],reverse=True)


def voice_vector(extractor,audio,intervals):
    vectors=[];seconds=0
    for a,b in intervals:
        while b-a>=1 and seconds<40:
            end=min(b,a+8,a+40-seconds)
            vector=embed(extractor,audio[int(a*16000):int(end*16000)])
            if vector is not None:vectors.append(vector);seconds+=end-a
            a=end
        if seconds>=40:break
    return (normalize(np.mean(vectors,axis=0)) if vectors else None),seconds


def match_voice(vector,people):
    if vector is None or not people:return None,None
    scores=sorted([(float(np.dot(vector,normalize(p['embedding']))),p) for p in people],key=lambda x:x[0],reverse=True)
    best,person=scores[0];second=scores[1][0] if len(scores)>1 else -1
    cfg=core.config()
    if best>=cfg.get('speaker_identity_threshold',0.65) and best-second>=cfg.get('speaker_identity_margin',0.10):
        return person,best
    return None,best


def enroll(source,name):
    name=' '.join(name.split())
    if not 2<=len(name)<=100:raise ValueError('Укажите имя сотрудника длиной от 2 до 100 символов.')
    core.database().close()
    diarizer,extractor=engines()
    with decoded_audio(source,core.ROOT/'state') as audio:
        if len(audio)>16000*180:raise ValueError('Образец голоса должен быть короче 3 минут.')
        turns=[{'start':r.start,'end':r.end,'speaker':r.speaker} for r in diarizer.process(audio).sort_by_start_time()]
        ids={t['speaker'] for t in turns}
        # Ignore segmentation fragments that cannot supply a usable voice sample.
        ids={sid for sid in ids if sum(b-a for a,b in clean_intervals(turns,sid))>=2}
        if len(ids)!=1:raise ValueError('Нужна запись одного человека без посторонних голосов и музыки.')
        intervals=clean_intervals(turns,next(iter(ids)))
        total=sum(b-a for a,b in intervals)
        if total<8:raise ValueError('Мало чистой речи. Запишите 20–40 секунд непрерывного разговора одного человека.')
        vector,seconds=voice_vector(extractor,audio,intervals)
        if vector is None:raise ValueError('Голос не распознан. Повторите запись ближе к микрофону.')
    # Enrollment is serialized by the recorder/enrollment manager.
    bank=registry()
    person=next((p for p in bank['people'] if p['name'].casefold()==name.casefold()),None)
    if person:
        old=normalize(person['embedding'])
        if float(np.dot(old,vector))<core.config().get('speaker_identity_threshold',0.65):
            raise ValueError('Образец не похож на сохранённый голос этого сотрудника. Проверьте имя и запись.')
        vector=normalize(old*person['samples']+vector)
        person.update(embedding=vector.tolist(),samples=person['samples']+1,speech_seconds=round(person['speech_seconds']+seconds,1))
    else:
        person={'id':uuid.uuid4().hex,'name':name,'embedding':vector.tolist(),'samples':1,'speech_seconds':round(seconds,1)}
        bank['people'].append(person)
    samples=person.setdefault('source_samples',[])
    resolved=str(Path(source).resolve())
    if resolved not in samples:samples.append(resolved)
    bank.update(version=2,embedding_model=paths()[1].name)
    core.save(core.ROOT/'voices/profiles.json',bank)
    return {k:person[k] for k in ('id','name','samples','speech_seconds')}


def label_interval(start,end,turns,names):
    overlaps={}
    for t in turns:
        overlap=max(0,min(end,t['end'])-max(start,t['start']))
        if overlap:overlaps[t['speaker']]=overlaps.get(t['speaker'],0)+overlap
    if not overlaps:return None,'Говорящий не определён',False
    ordered=sorted(overlaps,key=overlaps.get,reverse=True)
    # A word spanning a change or simultaneous speech is not confidently assigned.
    if len(ordered)>1 and overlaps[ordered[1]]>max(.06,(end-start)*.20):
        return None,'Несколько голосов / смена говорящего',True
    sid=ordered[0]
    if overlaps[sid]<max(.02,(end-start)*.35):return None,'Говорящий не определён',False
    return sid,names[sid],False


def assign_words(segments, turns, names):
    from itertools import chain, pairwise
    starts=[t['start'] for t in turns];max_ends=[]
    for turn in turns:max_ends.append(max(turn['end'],max_ends[-1] if max_ends else 0))
    rows=[]
    def intersect(left,right):
        return turns[bisect.bisect_right(max_ends,left):bisect.bisect_left(starts,right)]

    words = (word for segment in segments for word in
             (segment.get('words') or [{'start':segment['start'],'end':segment['end'],'word':' '+segment['text']}]))
    for word, following in pairwise(chain(words,[None])):
        start,end=word['start'],word['end']
        candidates=intersect(start,end)
        sid,name,ambiguous=label_interval(start,end,candidates,names)
        # ASR sometimes includes leading silence in the first word. Anchor its
        # audible tail to the next word only inside one uninterrupted voice turn.
        if sid is None and following and len(candidates)==1 and 0<=following['start']-end<=0.15:
            turn=candidates[0]
            next_turns=intersect(following['start'],following['end'])
            tail=end-turn['start']
            if (start<turn['start'] and tail>=max(.30,.20*(end-start))
                    and next_turns==candidates and following['start']+.20<=turn['end']
                    and label_interval(following['start'],following['end'],next_turns,names)[0]==turn['speaker']):
                sid=turn['speaker']
                name=names[sid]
        if rows and rows[-1]['speaker']==name and start-rows[-1]['end']<1.2:
            rows[-1]['end']=end;rows[-1]['text']+=word['word'];rows[-1]['words'].append(word)
        else:
            rows.append({'start':start,'end':end,'text':word['word'],'speaker':name,'speaker_id':sid,'ambiguous':ambiguous,'words':[word]})
    for row in rows:row['text']=row['text'].strip()
    return rows


def diarize(source,transcript):
    transcript=Path(transcript)
    data=json.loads(transcript.read_text(encoding='utf-8'))
    diarizer,extractor=engines()
    from long_audio import windows, checkpoint_dir, WINDOW
    bank=registry();names={};identities={};representatives={};turns=[]
    cache=checkpoint_dir(transcript.parent,'speakers',source,{'config':core.config(),'profiles':bank})
    with decoded_audio(source,transcript.parent) as audio:
        for index,(begin,end,offset,samples) in enumerate(windows(audio)):
            core.save(transcript.parent/'progress.json',{'stage':'diarizing','part':index+1,
                'total':max(1,int(np.ceil(len(audio)/16000/WINDOW)))})
            path=cache/f'{index:05d}.json'
            if path.exists():
                part=json.loads(path.read_text(encoding='utf-8'))
            else:
                local=[{'start':float(r.start),'end':float(r.end),'speaker':int(r.speaker)}
                    for r in diarizer.process(samples).sort_by_start_time()]
                voices={}
                for sid in sorted(set(t['speaker'] for t in local)):
                    vector,seconds=voice_vector(extractor,samples,clean_intervals(local,sid))
                    voices[str(sid)]={'vector':vector.tolist() if vector is not None else None,'seconds':seconds}
                part={'turns':local,'voices':voices}
                core.save(path,part)
            mapping={};used=set()
            for local_id,voice in part['voices'].items():
                vector=normalize(voice['vector']) if voice['vector'] is not None else None
                seconds=voice['seconds']
                person,similarity=match_voice(vector,bank['people']) if seconds>=2 else (None,None)
                sid=None
                if person:
                    sid=next((int(k) for k,v in identities.items() if v['person_id']==person['id']),None)
                elif vector is not None and seconds>=2:
                    # Conservative cross-window association. Never silently reuse an
                    # unknown label merely because its local cluster number repeats.
                    scores=sorted(((float(np.dot(vector,v)),k) for k,v in representatives.items()
                        if k not in used and identities[str(k)]['person_id'] is None),reverse=True)
                    if scores and scores[0][0]>=0.75 and (len(scores)==1 or scores[0][0]-scores[1][0]>=0.10):
                        sid=scores[0][1]
                if sid is None:
                    sid=len(names)
                    names[sid]=person['name'] if person else f'Участник {sid+1} (имя не определено)'
                    identities[str(sid)]={'name':names[sid],'person_id':person['id'] if person else None,
                        'similarity':similarity,'clean_seconds':seconds}
                    if vector is not None and seconds>=2:representatives[sid]=vector
                used.add(sid);mapping[int(local_id)]=sid
            for turn in part['turns']:
                left,right=max(begin,offset+turn['start']),min(end,offset+turn['end'])
                if right>left:turns.append({'start':left,'end':right,'speaker':mapping[turn['speaker']]})
    turns.sort(key=lambda t:t['start'])
    rows=assign_words(data['segments'],turns,names)
    data.update(segments=rows,speaker_turns=turns,identities=identities,speaker_status='identified',voice_profiles=len(bank['people']),
                unknown_speakers=sum(x['person_id'] is None for x in identities.values()))
    core.save(transcript,data)


if __name__=='__main__':
    try:
        if sys.argv[1]=='enroll':core.save(Path(sys.argv[4]),enroll(sys.argv[2],sys.argv[3]))
        elif sys.argv[1]=='diarize':diarize(sys.argv[2],sys.argv[3])
    except Exception as exc:
        print(str(exc),file=sys.stderr);sys.exit(1)
