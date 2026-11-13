"""Two-source session archives. Preserve original audio and source identity."""
import copy
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

import meeting_ai as core


def manifest(archive):
    entries=archive.infolist()
    names=[e.filename for e in entries]
    name_set=set(names)
    if len(names)!=len(name_set) or len(names)>100000:
        raise ValueError('Повторяющиеся файлы или слишком большой список файлов.')
    if 'session.json' not in name_set or archive.getinfo('session.json').file_size>1024*1024:
        raise ValueError('Нет корректного описания встречи.')
    data=json.loads(archive.read('session.json').decode('utf-8-sig'))
    if data.get('status') not in {'stopped','capture_error'}:
        raise ValueError('Сначала завершите запись.')
    sources=data.get('sources',[])
    if not isinstance(sources,list) or len(sources)>2:
        raise ValueError('Неверный список источников.')
    seen=set();files=set()
    for source in sources:
        if not isinstance(source,dict) or source.get('source') not in {'microphone','computer'} or source['source'] in seen:
            raise ValueError('Неверный источник звука.')
        seen.add(source['source'])
        for part in source.get('segments',[]):
            name=part['file']
            if not isinstance(name,str) or '/' in name or '\\' in name or ':' in name or not name.endswith(('.wav','.webm','.mp4','.ogg')) or name not in name_set or name in files:
                raise ValueError('Неверное имя аудиофайла.')
            files.add(name)
            for key in ('firstPacketSeconds','audioSeconds'):
                value=part[key]
                if not isinstance(value,(int,float)) or not math.isfinite(value) or value<0:
                    raise ValueError('Неверные временные метки.')
    if not files:raise ValueError('В записи нет аудиоданных ни одного источника.')
    if name_set!=files|{'session.json'}:raise ValueError('В пакете есть посторонние файлы.')
    return data


def validate(path):
    with zipfile.ZipFile(path) as z:
        data=manifest(z)
        # Disk budget, not a duration limit. Decode/ASR need additional working space.
        size=sum(i.file_size for i in z.infolist())
        if size*4+1024**3>shutil.disk_usage(core.ROOT).free:
            raise ValueError('Недостаточно места для распаковки и обработки встречи.')
        return data


def merge(parts, warnings):
    result={'language':'ru','duration':0,'segments':[],'identities':{},
            'speaker_status':'identified','capture_warnings':warnings,'unknown_speakers':0}
    keys={}
    for source,offset,data in parts:
        result['duration']=max(result['duration'],offset+data.get('duration',0))
        mapping={}
        for local,identity in data.get('identities',{}).items():
            person=identity.get('person_id')
            key=('person',person) if person else (source,local)
            if key not in keys:
                sid=len(keys);keys[key]=sid
                entry=copy.deepcopy(identity)
                if not person:
                    entry['name']=('Комната' if source=='microphone' else 'Звонок')+' — '+entry['name']
                    result['unknown_speakers']+=1
                result['identities'][str(sid)]=entry
            mapping[local]=keys[key]
        for row in data['segments']:
            row=copy.deepcopy(row);row['source']=source
            row['start']+=offset;row['end']+=offset
            for word in row.get('words',[]):word['start']+=offset;word['end']+=offset
            sid=mapping.get(str(row.get('speaker_id')))
            row['speaker_id']=sid
            if sid is not None:row['speaker']=result['identities'][str(sid)]['name']
            result['segments'].append(row)
    result['segments'].sort(key=lambda r:(r['start'],r['source']))
    return result


def process(path,destination, force_diarize=False):
    """Analyze each source separately, with gaps restored on disk before diarization."""
    import numpy as np
    from audio_io import decoded_audio
    destination=Path(destination);folder=destination.parent/'session-sources';folder.mkdir(exist_ok=True)
    data=validate(path);warnings=[];results=[]
    with zipfile.ZipFile(path) as z:
        for source in data['sources']:
            label=source['source'];base=folder/label;base.mkdir(exist_ok=True)
            if source.get('error'):warnings.append(label+': '+source['error'])
            parts=source.get('segments',[])
            if not parts:
                warnings.append(label+': аудиоданные не поступили; источник не записан.');continue
            if data.get('expectedSources') and not source.get('error') and source.get('maxPeak',1)<=.0001:
                continue  # Captured silence isn't an interrupted recording.
            # Float raw file can grow past WAV's 4 GB limit; sparse gaps retain the timeline.
            raw=base/'timeline.f32';wav=base/'timeline.wav'
            if not wav.exists():
                with raw.open('w+b') as target:
                    for part in sorted(parts,key=lambda p:p['firstPacketSeconds']):
                        local=base/part['file']
                        with z.open(part['file']) as src,local.open('wb') as dst:shutil.copyfileobj(src,dst)
                        with decoded_audio(local,base) as audio:
                            start=part.get('startSeconds',part['firstPacketSeconds'])
                            if not isinstance(start,(int,float)) or not math.isfinite(start) or start<0:
                                raise ValueError('Неверное начало сегмента.')
                            if start>data.get('elapsedSeconds',0)+2:raise ValueError('Сегмент за пределами встречи.')
                            if int(start*16000)*4+len(audio)*4>shutil.disk_usage(base).free:
                                raise ValueError('Недостаточно места для временной шкалы.')
                            target.seek(int(start*16000)*4)
                            for n in range(0,len(audio),16000*60):target.write(audio[n:n+16000*60].tobytes())
                # RF64 avoids a fixed duration limit; ffmpeg handles the disk-backed conversion.
                exe=core.ROOT.parent/'protocol-employee/ffmpeg/bin/ffmpeg.exe'
                temporary=base/'timeline.partial.wav'
                subprocess.run([str(exe),'-v','error','-nostdin','-y','-f','f32le','-ar','16000','-ac','1','-i',str(raw),'-c:a','pcm_s16le','-rf64','auto',str(temporary)],check=True)
                temporary.replace(wav)
                raw.unlink()
            transcript=base/'transcript.json'
            if not transcript.exists():
                subprocess.run([sys.executable,str(core.ROOT/'meeting_ai.py'),'_asr',str(wav),str(transcript)],check=True)
            text=json.loads(transcript.read_text(encoding='utf-8'))
            if (force_diarize or text.get('speaker_status')!='identified') and text['segments']:
                subprocess.run([sys.executable,str(core.ROOT/'speakers.py'),'diarize',str(wav),str(transcript)],check=True)
                text=json.loads(transcript.read_text(encoding='utf-8'))
            if not text['segments']:warnings.append(label+': разборчивая речь не обнаружена.')
            results.append((label,0,text))
    present={s['source'] for s in data['sources']}
    expected=data.get('expectedSources',['microphone','computer'])
    for missing in set(expected)-present:warnings.append(missing+': источник отсутствует.')
    core.save(destination,merge(results,warnings))
