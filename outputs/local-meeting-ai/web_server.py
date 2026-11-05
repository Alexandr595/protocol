"""Loopback-only web interface. Standard library, no remote assets or services."""
import json
import mimetypes
import os
from pathlib import Path
import re
import shutil
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import uuid

import meeting_ai as core
from folder_watch import FolderWatcher
import speakers
from recording import Recorder
from network_access import NetworkAccess
from record_lifecycle import change as change_record

PORT = int(os.environ.get('MEETING_UI_PORT', '18765'))
ORIGIN = f'http://127.0.0.1:{PORT}'
ROOT = core.ROOT
network = NetworkAccess(ROOT)
worker = None
stop_event = threading.Event()
shutting_down = threading.Event()
control_lock = threading.Lock()
upload_lock = threading.Lock()
worker_error = ''
watcher = None
recorder = Recorder()


def start_worker():
    global worker, worker_error
    if shutting_down.is_set():return False
    if not readiness()['ready']:
        return False
    with control_lock:
        if watcher and not watcher.snapshot()['processing_enabled']:
            return False
        if not worker or not worker.is_alive():
            worker_error = ''
            stop_event.clear()
            worker = threading.Thread(target=work, daemon=True)
            worker.start()
    return True


def monitor_folder():
    while True:
        try:
            watcher.scan()
            if watcher.snapshot()['processing_enabled'] and not worker_error:
                start_worker()
        except Exception as exc:
            with watcher.lock:
                watcher.error = str(exc)
        time.sleep(5)


def read_json(path, fallback=None):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return fallback


def readiness():
    cfg = core.config()
    speech = core.resolve(cfg['asr_model'])
    asr = all((speech / p).is_file() for p in ['model.bin', 'config.json', 'tokenizer.json', 'vocabulary.json'])
    summary = core.resolve(cfg['summary_model']).is_file() and core.resolve(cfg['llama_exe']).is_file()
    voices = speakers.available()
    return {'asr': asr, 'summary': summary, 'speakers': voices, 'ready': asr and summary and voices,
            'summary_name': Path(cfg['summary_model']).stem, 'summary_context': cfg['summary_context']}


def job(key):
    if not re.fullmatch(r'[a-f0-9]{64}', key):
        return None
    with core.database() as db:
        row = db.execute('SELECT * FROM jobs WHERE id=?', (key,)).fetchone()
    return dict(row) if row else None


def trash_records():
    with core.database() as db:
        return [dict(r) for r in db.execute("SELECT id,name,deleted_at FROM jobs WHERE status='deleted' ORDER BY deleted_at DESC")]


def public_job(row):
    row = dict(row)
    row.pop('path', None)
    folder = ROOT / 'results' / row['id'][:16]
    row['progress'] = read_json(folder / 'progress.json', {}) if row['status'] == 'running' else {}
    row['has_transcript'] = (folder / 'transcript.json').is_file()
    row['has_minutes'] = (folder / 'minutes.md').is_file()
    row['has_summary'] = (folder / 'summary.md').is_file()
    row['result_version'] = [(folder / f).stat().st_mtime_ns if (folder / f).exists() else 0 for f in ('transcript.json','summary.md','minutes.md')]
    return row


def work():
    global worker_error
    try:
        core.run(watch=True, stop_event=stop_event, collect=False, can_process=lambda: recorder.status not in {'recording','saving','enrolling'})
    except Exception as exc:
        worker_error = str(exc)


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *_):
        pass

    def valid_host(self):
        return network.valid_host(self.headers.get('Host'), PORT)

    def authenticate(self):
        if network.authorized(self.client_address[0], self.headers.get('Authorization')): return True
        self.close_connection = True
        self.respond(401, {'error': 'Введите логин и пароль для доступа по локальной сети.'},
                     extra={'WWW-Authenticate': 'Basic realm="Meeting AI", charset="UTF-8"', 'Connection':'close'})
        return False

    def respond(self, status, body, kind='application/json; charset=utf-8', extra=None):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        if extra:
            for name, value in extra.items():
                self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            self.get()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception as exc:
            self.respond(500, {'error': str(exc)})

    def get(self):
        if not self.valid_host():
            self.respond(403, {'error': 'Недопустимый адрес'})
            return
        path = urllib.parse.urlsplit(self.path).path
        if not self.authenticate(): return
        static = {'/': 'index.html', '/app.js': 'app.js', '/queue-ui.js':'queue-ui.js', '/recording-ui.js':'recording-ui.js', '/style.css': 'style.css', '/dark.css':'dark.css', '/lifecycle-ui.js':'lifecycle-ui.js'}
        if path in static:
            file = ROOT / 'web' / static[path]
            self.respond(200, file.read_bytes(), (mimetypes.guess_type(str(file))[0] or 'text/plain') + '; charset=utf-8')
        elif path == '/ProtocolSetup.msi':
            file=ROOT/'dist/ProtocolSetup.msi'
            if file.is_file():self.respond(200,file.read_bytes(),'application/octet-stream',{'Content-Disposition':'attachment; filename="ProtocolSetup.msi"'})
            else:self.respond(404,{'error':'Установщик ещё не собран.'})
        elif path == '/client.zip':
            file=ROOT/'dist/MeetingAI-Client-Windows.zip'
            if file.exists():self.audio(file)
            else:self.respond(404,{'error':'Пакет клиента ещё не собран.'})
        elif path == '/audio-check.zip':
            file=ROOT/'dist/Protocol-AudioCheck.zip'
            if file.is_file():
                self.respond(200, file.read_bytes(), 'application/zip',
                             {'Content-Disposition': 'attachment; filename="Protocol-AudioCheck.zip"'})
            else:self.respond(404,{'error':'Пакет диагностики ещё не собран.'})
        elif path == '/api/state':
            with core.database() as db:
                rows = db.execute("SELECT * FROM jobs WHERE status!='deleted' ORDER BY CASE status WHEN 'running' THEN 0 WHEN 'queued' THEN 1 WHEN 'held' THEN 2 ELSE 3 END, CASE WHEN status='queued' THEN -priority ELSE 0 END, CASE WHEN status='queued' THEN created ELSE -created END LIMIT 300").fetchall()
                counts = dict(db.execute("SELECT status,COUNT(*) FROM jobs WHERE status!='deleted' GROUP BY status").fetchall())
            self.respond(200, {'jobs': [public_job(r) for r in rows], 'models': readiness(),
                'worker': bool(worker and worker.is_alive()), 'stopping': stop_event.is_set(),
                'worker_error': worker_error, 'folder': watcher.snapshot() if watcher else None, 'counts':counts,
                'trash':trash_records(), 'recording':recorder.snapshot(), 'profiles':speakers.public_profiles(), 'recoverable':recorder.recoverable()})
        elif path == '/api/devices':
            self.respond(200, {'devices':recorder.devices(), 'settings':recorder.settings()})
        elif path == '/api/recording':
            self.respond(200,recorder.snapshot())
        elif match := re.fullmatch(r'/api/jobs/([a-f0-9]{64})(?:/(audio|transcript|summary|minutes|mic|system))?', path):
            row = job(match[1])
            if not row:
                self.respond(404, {'error': 'Запись не найдена'})
                return
            folder = ROOT / 'results' / row['id'][:16]
            if match[2] == 'audio':
                self.audio(Path(row['path']))
            elif match[2] in {'mic','system'}:
                capture=read_json(ROOT/'inbox'/(row['id']+'.capture.json'),{})
                session=Path(capture.get('session','')).resolve()
                file=session/(match[2]+'.wav')
                if not session.is_relative_to((ROOT/'recordings').resolve()) or not file.is_file():
                    self.respond(404,{'error':'Исходная дорожка не найдена'})
                else: self.audio(file)
            elif match[2] in {'transcript', 'summary', 'minutes'}:
                filename = 'transcript.txt' if match[2] == 'transcript' else match[2]+'.md'
                if not (folder / filename).exists():
                    self.respond(404, {'error': 'Результат ещё не готов'})
                else:
                    self.respond(200, (folder / filename).read_bytes(), 'text/plain; charset=utf-8',
                                 {'Content-Disposition': f'attachment; filename="{filename}"'})
            else:
                result = public_job(row)
                capture=read_json(ROOT/'inbox'/(row['id']+'.capture.json'),{})
                result['capture']={'folder':capture.get('session'), 'sources':[t['kind'] for t in capture.get('tracks',[])], 'warning':capture.get('warning','')}
                result['transcript'] = read_json(folder / 'transcript.json', None)
                result['minutes'] = (folder/'minutes.md').read_text(encoding='utf-8') if (folder/'minutes.md').exists() else None
                result['summary'] = (folder / 'summary.md').read_text(encoding='utf-8') if (folder / 'summary.md').is_file() else None
                self.respond(200, result)
        else:
            self.respond(404, {'error': 'Не найдено'})

    def audio(self, path):
        size = path.stat().st_size
        start, end, status = 0, size - 1, 200
        header = self.headers.get('Range')
        if header:
            match = re.fullmatch(r'bytes=(\d*)-(\d*)', header)
            if not match or not any(match.groups()):
                self.respond(416, b'', extra={'Content-Range': f'bytes */{size}'})
                return
            if match[1]:
                start = int(match[1])
                end = min(int(match[2]), end) if match[2] else end
            else:
                start = max(0, size - int(match[2]))
            if start > end or start >= size:
                self.respond(416, b'', extra={'Content-Range': f'bytes */{size}'})
                return
            status = 206
        self.send_response(status)
        self.send_header('Content-Type', mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Content-Length', str(end - start + 1))
        self.send_header('Cache-Control', 'no-store')
        if status == 206:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.end_headers()
        with path.open('rb') as stream:
            stream.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                block = stream.read(min(256 * 1024, remaining))
                if not block:
                    break
                self.wfile.write(block)
                remaining -= len(block)

    def do_POST(self):
        global worker, worker_error
        # Custom header + same-origin policy prevents cross-site form submissions.
        if (not self.valid_host() or self.headers.get('X-Local-App') != 'meeting-ai'
                or self.headers.get('Origin') not in {None, 'http://' + self.headers.get('Host', '')}):
            self.close_connection = True
            # Consume small rejected requests so Windows does not reset the socket
            # with an unread body before the client receives the error response.
            try:
                length=int(self.headers.get('Content-Length','0'))
                if 0 < length <= 65536:
                    self.connection.settimeout(1)
                    self.rfile.read(length)
            except (OSError,ValueError):
                pass
            self.respond(403, {'error': 'Запрос разрешён только из локального интерфейса'})
            return
        if not self.authenticate(): return
        try:
            if shutting_down.is_set():raise ValueError('Сервер останавливается.')
            path = urllib.parse.urlsplit(self.path).path
            data = {}
            if path not in {'/api/upload','/api/voices/upload'}:
                length = int(self.headers.get('Content-Length','0'))
                if length > 8192 or length < 0:
                    raise ValueError('Слишком большой запрос')
                data = json.loads(self.rfile.read(length)) if length else {}
                if not isinstance(data,dict):
                    raise ValueError('Неверный формат запроса')
            if path == '/api/upload':
                self.upload()
            elif path == '/api/shutdown':
                if self.client_address[0] != '127.0.0.1':raise ValueError('Останавливать сервер можно только на самом сервере.')
                with recorder.lock, control_lock:
                    if recorder.busy():raise ValueError('Сначала завершите запись.')
                    if worker and worker.is_alive():raise ValueError('Сначала приостановите очередь в вебке и дождитесь завершения текущей обработки.')
                    stop_event.set()
                    shutting_down.set()
                    self.respond(200,{'ok':True})
                    threading.Thread(target=self.server.shutdown,daemon=True).start()
            elif path == '/api/voices/upload':
                self.upload(voice=True)
            elif match := re.fullmatch(r'/api/jobs/([a-f0-9]{64})/(trash|restore|summarize)',path):
                change_record(match[1],match[2])
                self.respond(200,{'ok':True})
            elif path == '/api/recording/start':
                self.respond(200,recorder.start(data.get('device'),data.get('purpose','meeting'),data.get('name',''),data.get('system_device')))
            elif path == '/api/recording/stop':
                self.respond(200,recorder.stop())
            elif path == '/api/recording/recover':
                self.respond(200,recorder.recover(data.get('session')))
            elif path == '/api/recording/reset':
                self.respond(200,recorder.reset())
            elif path == '/api/recording/dismiss':
                self.respond(200,recorder.dismiss(data.get('session')))
            elif match := re.fullmatch(r'/api/jobs/([a-f0-9]{64})/recognize',path):
                key=match[1]
                with core.database() as db:
                    db.execute('BEGIN IMMEDIATE')
                    row=db.execute('SELECT status FROM jobs WHERE id=?',(key,)).fetchone()
                    if not row or row['status'] not in {'done','needs_review','needs_speaker_setup'}:
                        raise ValueError('Дождитесь завершения обработки записи.')
                    folder=ROOT/'results'/key[:16]
                    transcript=read_json(folder/'transcript.json')
                    if transcript is None:raise ValueError('Расшифровка не найдена.')
                    archive=folder/('previous-'+uuid.uuid4().hex[:8]);archive.mkdir()
                    for filename in ('transcript.json','transcript.txt','summary.md','minutes.md'):
                        if (folder/filename).exists():shutil.copy2(folder/filename,archive/filename)
                    transcript['speaker_status']='pending'
                    core.save(folder/'transcript.json',transcript)
                    (folder/'summary.md').unlink(missing_ok=True)
                    db.execute("UPDATE jobs SET status='queued',error='',finished=NULL WHERE id=?",(key,))
                self.respond(200,{'ok':True})
            elif path == '/api/folder':
                if watcher is None:
                    raise ValueError('Наблюдение за папкой недоступно')
                settings = watcher.configure(data)
                self.respond(200,settings)
            elif match := re.fullmatch(r'/api/jobs/([a-f0-9]{64})/(priority|hold|resume)',path):
                key, action = match.groups()
                with core.database() as db:
                    if action == 'priority':
                        priority = data.get('priority')
                        if type(priority) is not int or priority not in {-10,0,10,20}:
                            raise ValueError('Неизвестный приоритет')
                        changed = db.execute("UPDATE jobs SET priority=? WHERE id=? AND status IN ('queued','held')",(priority,key)).rowcount
                    elif action == 'hold':
                        changed = db.execute("UPDATE jobs SET status='held' WHERE id=? AND status='queued'",(key,)).rowcount
                    else:
                        changed = db.execute("UPDATE jobs SET status='queued' WHERE id=? AND status='held'",(key,)).rowcount
                self.respond(200 if changed else 409,{'ok':bool(changed),'error':'' if changed else 'Статус уже изменился. Обновите очередь.'})
            elif path == '/api/start':
                if not readiness()['ready']:
                    self.respond(409, {'error': 'Сначала дождитесь скачивания моделей.'})
                    return
                if watcher:
                    watcher.configure({'processing_enabled':True})
                start_worker()
                self.respond(200, {'ok': True})
            elif path == '/api/pause':
                with control_lock:
                    if watcher:
                        watcher.configure({'processing_enabled':False})
                    stop_event.set()
                self.respond(200, {'ok': True})
            elif match := re.fullmatch(r'/api/retry/([a-f0-9]{64})', path):
                with core.database() as db:
                    changed = db.execute("UPDATE jobs SET status='queued',error='' WHERE id=? AND status='error'", (match[1],)).rowcount
                    db.commit()
                self.respond(200 if changed else 409, {'ok': bool(changed), 'error': '' if changed else 'Повтор доступен только для записи с ошибкой.'})
            else:
                self.respond(404, {'error': 'Не найдено'})
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception as exc:
            self.close_connection = True
            self.respond(400, {'error': str(exc)})

    def upload(self, voice=False):
        length = int(self.headers.get('Content-Length', '0'))
        name = urllib.parse.unquote(self.headers.get('X-Filename', ''))
        name = re.split(r'[/\\]', name)[-1]
        name = re.sub(r'[<>:"|?*\x00-\x1f]', '_', name).strip(' .')
        if length <= 0:
            raise ValueError('Запись должна быть непустой; требуется Content-Length.')
        person_name = urllib.parse.unquote(self.headers.get('X-Person-Name','')).strip()
        if voice and (length > 100*1024**2 or not 2<=len(person_name)<=100):
            raise ValueError('Укажите имя сотрудника и образец голоса до 100 МБ, короче 3 минут.')
        suffix = Path(name).suffix.lower()
        if suffix not in core.EXTENSIONS:
            if length <= 65536:
                self.connection.settimeout(1)
                self.rfile.read(length)
            raise ValueError('Поддерживаются WAV, MP3, M4A, MP4, FLAC, OGG, OPUS и WEBM.')
        if shutil.disk_usage(ROOT).free < length * 2 + 1024**3:
            raise ValueError('Недостаточно свободного места для записи и её рабочей копии.')
        temp = ROOT / 'state' / (uuid.uuid4().hex + suffix)
        try:
            self.connection.settimeout(120)
            with temp.open('wb') as stream:
                remaining = length
                while remaining:
                    block = self.rfile.read(min(1024 * 1024, remaining))
                    if not block:
                        raise ValueError('Загрузка прервалась. Повторите выбор файла.')
                    stream.write(block)
                    remaining -= len(block)
            with upload_lock:
                if voice:
                    with recorder.lock:
                        if recorder.thread and recorder.thread.is_alive():
                            raise ValueError('Дождитесь завершения текущей записи или сохранения голоса.')
                        samples=ROOT/'voices/samples';samples.mkdir(parents=True,exist_ok=True)
                        sample=samples/temp.name
                        temp.replace(sample)
                        result=recorder.import_voice(sample,person_name)
                    self.respond(200,result)
                    return
                key = core.add(temp)
                with core.database() as db:
                    # Preserve the original name on duplicates.
                    db.execute('UPDATE jobs SET name=? WHERE id=? AND name=?', (name, key, temp.name))
                    db.commit()
            self.respond(200, {'id': key})
        finally:
            temp.unlink(missing_ok=True)


if __name__ == '__main__':
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
    core.database().close()
    watcher = FolderWatcher()
    server = ThreadingHTTPServer((network.bind, PORT), Handler)
    core.save(ROOT/'state/server.json', {'pid':os.getpid(),'port':PORT})
    threading.Thread(target=monitor_folder,daemon=True).start()
    print('Локальный интерфейс:', ORIGIN, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        stop_event.set()
    finally:
        server.server_close()
