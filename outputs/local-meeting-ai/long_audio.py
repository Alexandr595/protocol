"""Process bounded audio windows; the original recording stays on disk."""
import hashlib
import json
from pathlib import Path

RATE = 16000
WINDOW = 15 * 60
OVERLAP = 3


def windows(audio):
    step = WINDOW * RATE
    for begin in range(0, len(audio), step):
        end = min(len(audio), begin + step)
        left, right = max(0, begin - OVERLAP * RATE), min(len(audio), end + OVERLAP * RATE)
        yield begin / RATE, end / RATE, left / RATE, audio[left:right]


def checkpoint_dir(folder, stage, source, settings):
    source = Path(source)
    key = hashlib.sha256(json.dumps([str(source.resolve()), source.stat().st_size,
        source.stat().st_mtime_ns, settings, WINDOW, OVERLAP, 3], sort_keys=True).encode()).hexdigest()
    path = Path(folder) / (stage+'-checkpoints') / key[:24]
    path.mkdir(parents=True, exist_ok=True)
    return path


def speech_regions(samples):
    from faster_whisper.vad import get_speech_timestamps, VadOptions
    return get_speech_timestamps(samples, VadOptions(min_silence_duration_ms=700,
        max_speech_duration_s=30, speech_pad_ms=400))


def transcribe(model, audio, folder, source, cfg, save):
    cache = checkpoint_dir(folder, 'asr', source, cfg)
    rows = []
    for index, (begin, end, offset, samples) in enumerate(windows(audio)):
        path = cache / f'{index:05d}.json'
        if path.exists():
            part = json.loads(path.read_text(encoding='utf-8'))
        else:
            part = []
            # Do not concatenate distant utterances after removing silence:
            # Whisper can collapse repeated phrases into a single occurrence.
            regions=speech_regions(samples)
            for region_index,region in enumerate(regions):
                left=max(0,region['start']-RATE);right=min(len(samples),region['end']+RATE)
                clip_offset=offset+left/RATE
                # Split ownership in the silence BETWEEN regions. Whisper often
                # timestamps the first word at clip zero, before the VAD start.
                own_left=max(begin,offset+(regions[region_index-1]['end']+region['start'])/(2*RATE)) if region_index else begin
                own_right=min(end,offset+(region['end']+regions[region_index+1]['start'])/(2*RATE)) if region_index+1<len(regions) else end
                segments, _ = model.transcribe(samples[left:right], language='ru', task='transcribe', beam_size=5,
                    vad_filter=False, word_timestamps=True, condition_on_previous_text=False)
                for segment in segments:
                    words = []
                    for word in segment.words or []:
                        item = dict(vars(word), start=word.start+clip_offset, end=word.end+clip_offset)
                        # Each boundary word belongs to one window; overlap supplies context.
                        if own_left <= (item['start']+item['end'])/2 < own_right:
                            words.append(item)
                    if words:
                        part.append({'start':words[0]['start'], 'end':words[-1]['end'],
                            'text':''.join(w['word'] for w in words).strip(), 'speaker':None, 'words':words})
                    elif not segment.words and own_left <= clip_offset+(segment.start+segment.end)/2 < own_right:
                        part.append({'start':clip_offset+segment.start, 'end':clip_offset+segment.end,
                            'text':segment.text.strip(), 'speaker':None, 'words':[]})
                save(Path(folder)/'progress.json', {'stage':'transcribing',
                    'seconds':min(end,offset+region['end']/RATE), 'duration':len(audio)/RATE})
            save(path, part)
        rows.extend(part)
        save(Path(folder)/'progress.json', {'stage':'transcribing', 'seconds':end, 'duration':len(audio)/RATE})
    return rows
