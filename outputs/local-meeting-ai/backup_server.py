"""Explicit offline backup of recordings, results, profiles and queue; no models."""
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parent
def main():
    try:
        urllib.request.urlopen('http://127.0.0.1:18765/api/state',timeout=2).close()
    except OSError:pass
    else:raise RuntimeError('Для согласованной копии сначала остановите сервер через Остановить сервер.cmd.')
    backup=ROOT/'backups';backup.mkdir(exist_ok=True)
    destination=backup/(time.strftime('server-%Y-%m-%d_%H-%M-%S')+'.zip')
    temporary=destination.with_suffix('.zip.part')
    with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED,compresslevel=1) as archive:
        for name in ['state','recordings','inbox','results','voices','incoming']:
            for file in (ROOT/name).rglob('*'):
                if file.is_file() and file.suffix not in {'.lnk','.log'}:
                    archive.write(file,file.relative_to(ROOT))
        archive.write(ROOT/'config.json','config.json')
    temporary.replace(destination)
    print('Backup:',destination)
    print('Copy this archive to a separate disk. It includes access credentials.')
if __name__=='__main__':main()
