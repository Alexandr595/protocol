"""Convert durable capture journals to aligned audio without loading a meeting into RAM."""
import json
import math
import struct
from pathlib import Path
import numpy as np

RATE = 16000
RIFF_MAX = 0xffffffff


def assemble(folder, metadata):
    folder = Path(folder)
    count = int(math.ceil(metadata['duration'] * RATE))
    if count < RATE:
        raise ValueError('Запись короче одной секунды. Исходные данные сохранены.')
    maps = []
    temporary = []
    total_frames = 0
    try:
        for track in metadata['tracks']:
            kind = track['kind']
            temp = folder / (kind + '.aligned.pcm')
            temporary.append(temp)
            target = np.memmap(temp, dtype='<i2', mode='w+', shape=(count,))
            maps.append(target)
            target[:] = 0
            channels, rate = track['channels'], track['rate']
            previous_end = 0
            with (folder / (kind + '.pcm')).open('rb') as source, (folder / (kind + '.jsonl')).open(encoding='utf-8') as journal:
                for line in journal:
                    if not line.strip(): continue
                    try: event = json.loads(line)
                    except ValueError:
                        if not line.endswith('\n'): break  # interrupted final journal write
                        raise
                    start = float(event['time'])
                    frames = int(event['frames'])
                    if not math.isfinite(start) or frames < 0 or frames > rate * 2:
                        raise ValueError('Повреждён журнал записи. Исходники сохранены.')
                    source.seek(event['offset'])
                    raw = source.read(frames * channels * 2)
                    if len(raw) != frames * channels * 2:
                        raise ValueError('Неполный исходник записи. Исходники сохранены.')
                    total_frames += frames
                    samples = np.frombuffer(raw, dtype='<i2').reshape(-1, channels).mean(axis=1)
                    left = max(previous_end, 0, math.ceil(start * RATE))
                    right = min(count, math.ceil((start + frames / rate) * RATE))
                    if right <= left: continue
                    positions = (np.arange(left, right) / RATE - start) * rate
                    target[left:right] = np.clip(np.interp(positions, np.arange(frames), samples), -32768, 32767).astype('<i2')
                    previous_end = right
            target.flush()
            write_wav(folder / (kind + '.wav'), [target], count)
        if not total_frames: raise ValueError('Устройства не передали звук. Проверьте выбранные источники.')
        destination = folder / 'meeting.wav'
        write_wav(destination, maps, count)
        return destination
    finally:
        for mapped in maps:
            mapped._mmap.close()
        for path in temporary:
            path.unlink(missing_ok=True)


def wav_header(count):
    """Use RF64 beyond RIFF's 32-bit sizes; sample counts remain 64-bit."""
    size = count * 2
    fmt = struct.pack('<4sIHHIIHH', b'fmt ', 16, 1, 1, RATE, RATE * 2, 2, 16)
    if size + 36 <= RIFF_MAX:
        return struct.pack('<4sI4s', b'RIFF', size + 36, b'WAVE') + fmt + struct.pack('<4sI', b'data', size)
    return (struct.pack('<4sI4s', b'RF64', 0xffffffff, b'WAVE') +
            struct.pack('<4sIQQQI', b'ds64', 28, size + 72, size, count, 0) +
            fmt + struct.pack('<4sI', b'data', 0xffffffff))


def write_wav(path, sources, count):
    partial = Path(str(path) + '.part')
    with partial.open('wb') as output:
        output.write(wav_header(count))
        for start in range(0, count, RATE * 10):
            # Fixed gain avoids clipping and preserves relative levels; originals remain separate.
            block = sum(s[start:start + RATE * 10].astype(np.float32) for s in sources) / len(sources)
            output.write(np.clip(block, -32768, 32767).astype('<i2').tobytes())
    partial.replace(path)
