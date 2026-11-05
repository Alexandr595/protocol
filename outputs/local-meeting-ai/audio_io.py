"""Decode to temporary PCM on disk instead of retaining thousands of arrays in RAM."""
from contextlib import contextmanager
import tempfile


@contextmanager
def decoded_audio(source, scratch):
    import av
    import numpy as np
    with tempfile.TemporaryFile(mode='w+b',dir=scratch) as pcm:
        resampler=av.AudioResampler(format='flt',layout='mono',rate=16000)
        with av.open(source,mode='r') as container:
            if not container.streams.audio:
                raise ValueError('В файле нет звуковой дорожки.')
            for frame in container.decode(audio=0):
                for converted in resampler.resample(frame):
                    pcm.write(converted.to_ndarray().astype(np.float32,copy=False).tobytes())
            for converted in resampler.resample(None):
                pcm.write(converted.to_ndarray().astype(np.float32,copy=False).tobytes())
        if not pcm.tell():
            raise ValueError('Не удалось прочитать звук из файла.')
        pcm.flush()
        audio=np.memmap(pcm,dtype=np.float32,mode='r')
        try:
            yield audio
        finally:
            audio._mmap.close()
