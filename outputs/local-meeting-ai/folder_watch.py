"""Folder discovery is independent of the inference worker and uses persisted signatures."""
import contextlib
import json
import os
from pathlib import Path
import threading
import time

import meeting_ai as core


@contextlib.contextmanager
def locked_reader(path):
    """Deny concurrent writes/deletion while importing; fail if a writer is already open."""
    if os.name != 'nt':
        with path.open('rb') as stream:
            yield stream
        return
    import ctypes
    import msvcrt
    from ctypes import wintypes
    create = ctypes.WinDLL('kernel32', use_last_error=True).CreateFileW
    create.argtypes = [wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    handle = create(str(path), 0x80000000, 1, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise OSError(ctypes.get_last_error(), 'Файл занят записью или недоступен')
    try:
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except Exception:
        close = ctypes.WinDLL('kernel32').CloseHandle
        close.argtypes = [wintypes.HANDLE]
        close(handle)
        raise
    with os.fdopen(fd, 'rb') as stream:
        yield stream


class FolderWatcher:
    def __init__(self, root=None):
        self.root = root or core.ROOT
        self.settings_path = self.root / 'state/folder-settings.json'
        self.lock = threading.RLock()
        defaults = {'folder':str((self.root/'incoming').resolve()),'enabled':True,'settle_seconds':60,
                    'mode':'stable','processing_enabled':True}
        try:
            defaults.update(json.loads(self.settings_path.read_text(encoding='utf-8')))
        except (OSError,ValueError):
            pass
        self.settings = defaults
        self.seen = {}
        self.pending = []
        self.error = ''
        self.last_scan = None

    def configure(self, changes):
        allowed = {'folder','enabled','settle_seconds','mode','processing_enabled'}
        if set(changes)-allowed:
            raise ValueError('Неизвестная настройка')
        with self.lock:
            updated = {**self.settings, **changes}
            folder = Path(updated['folder']).expanduser().resolve()
            if 'folder' in changes and not folder.is_dir():
                raise ValueError('Папка не существует или недоступна. Укажите существующую папку.')
            for name in ('inbox','results','state','voices','web'):
                if folder.is_relative_to((self.root/name).resolve()):
                    raise ValueError('Выберите папку записей вне служебных папок программы.')
            if updated['mode'] not in {'stable','ready'}:
                raise ValueError('Неизвестный режим готовности файлов')
            if type(updated['settle_seconds']) is not int or not 10 <= updated['settle_seconds'] <= 3600:
                raise ValueError('Ожидание готовности: от 10 до 3600 секунд')
            if any(type(updated[k]) is not bool for k in ('enabled','processing_enabled')):
                raise ValueError('Неверное значение переключателя')
            updated['folder'] = str(folder)
            core.save(self.settings_path, updated)
            if any(updated[k] != self.settings[k] for k in ('folder','mode','settle_seconds','enabled')):
                self.seen.clear()
                self.pending = []
                self.error = ''
            self.settings = updated
            return dict(updated)

    def snapshot(self):
        with self.lock:
            return {**self.settings,'pending':list(self.pending),'error':self.error,'last_scan':self.last_scan}

    def scan(self, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            cfg = dict(self.settings)
        if not cfg['enabled']:
            return
        folder = Path(cfg['folder'])
        pending, paths = [], set()
        try:
            # No recursive search: work stays proportional to the selected directory.
            candidates = sorted((p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in core.EXTENSIONS), key=lambda p:p.name)
            with core.database() as db:
                known = {r['path']: (r['size'],r['mtime']) for r in db.execute('SELECT * FROM imported_sources')}
            for path in candidates:
                with self.lock:
                    if cfg != self.settings:
                        return
                key = str(path.resolve())
                paths.add(key)
                try:
                    stat = path.stat()
                    signature = (stat.st_size, stat.st_mtime_ns)
                    if known.get(key) == signature:
                        self.seen.pop(key, None)
                        continue
                    previous = self.seen.get(key)
                    if not previous or previous[0] != signature:
                        self.seen[key] = (signature, now)
                    elapsed = now - self.seen[key][1]
                    marker = Path(str(path)+'.ready')
                    ready = marker.is_file() if cfg['mode']=='ready' else elapsed >= cfg['settle_seconds']
                    if not stat.st_size or not ready:
                        pending.append({'name':path.name,'reason':'Ожидает завершения записи' if cfg['mode']=='ready' else 'Проверяем, что файл больше не меняется'})
                        continue
                    with locked_reader(path) as stream:
                        if (path.stat().st_size,path.stat().st_mtime_ns) != signature:
                            self.seen.pop(key,None)
                            continue
                        job_id = core.add(path, source_stream=stream)
                    with core.database() as db:
                        db.execute('INSERT OR REPLACE INTO imported_sources VALUES(?,?,?,?)',(key,*signature,job_id))
                    self.seen.pop(key,None)
                except OSError:
                    pending.append({'name':path.name,'reason':'Файл занят или недоступен; повторим проверку'})
                except Exception as exc:
                    pending.append({'name':path.name,'reason':str(exc)})
            for key in list(self.seen):
                if key not in paths:
                    self.seen.pop(key,None)
            error = ''
        except OSError as exc:
            error = 'Папка недоступна: ' + str(exc)
        with self.lock:
            if cfg == self.settings:
                self.pending, self.error, self.last_scan = pending[:100], error, time.time()
