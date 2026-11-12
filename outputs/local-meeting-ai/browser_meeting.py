"""Accept a browser meeting as ordered audio blobs and publish one normal queue item."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import urllib.parse
import zipfile

import meeting_ai as core


def receive(handler):
    length = int(handler.headers.get('Content-Length', '0'))
    meta = json.loads(urllib.parse.unquote(handler.headers['X-Meeting']))
    tracks = meta['tracks']
    names = [t['source'] for t in tracks]
    if names not in (['microphone'], ['computer'], ['microphone', 'computer']):
        raise ValueError('Неверные источники встречи.')
    seconds = meta['seconds']
    if not isinstance(seconds, (float, int)) or not 0 < seconds < float('inf'):
        raise ValueError('Неверная длительность записи.')
    if any(type(t['size']) is not int or t['size'] <= 0 or t['ext'] not in ('webm','mp4','ogg') for t in tracks):
        raise ValueError('Неверные аудиодорожки.')
    if length != sum(t['size'] for t in tracks) or length*3 + 1024**3 > shutil.disk_usage(core.ROOT).free:
        raise ValueError('Проверьте размер записи и свободное место на сервере.')
    title = str(meta.get('title','')).strip()[:100] or 'Встреча'
    fd, path = tempfile.mkstemp(suffix='.meeting', dir=core.ROOT/'state')
    os.close(fd)
    try:
        handler.connection.settimeout(120)
        sources = []
        with zipfile.ZipFile(path, 'w') as z:
            for t in tracks:
                filename = t['source']+'.'+t['ext']
                entry = zipfile.ZipInfo(filename)
                entry.file_size = t['size']
                with z.open(entry, 'w', force_zip64=True) as out:
                    remaining = t['size']
                    while remaining:
                        block = handler.rfile.read(min(remaining, 1024**2))
                        if not block:
                            raise ValueError('Передача прервалась.')
                        out.write(block)
                        remaining -= len(block)
                sources.append(dict(source=t['source'], segments=[dict(file=filename,firstPacketSeconds=0,audioSeconds=seconds)]))
            reason = str(meta.get('interrupted',''))[:200]
            if reason:
                for source in sources:
                    source['error'] = reason
            z.writestr(zipfile.ZipInfo('session.json'), json.dumps(dict(status='capture_error' if reason else 'stopped',
                       expectedSources=names, sources=sources, elapsedSeconds=seconds)))
        key = core.add(path)
        with core.database() as db:
            db.execute('UPDATE jobs SET name=? WHERE id=? AND name=?',(title,key,Path(path).name))
        return {'id':key}
    finally:
        Path(path).unlink(missing_ok=True)
