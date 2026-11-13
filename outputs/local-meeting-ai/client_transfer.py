"""Durable client outbox and streaming authenticated uploads. No AI models."""
import base64
import ctypes
import http.client
import json
import re
import urllib.parse
from pathlib import Path
import meeting_ai as core


def protect(text, decrypt=False):
    class Blob(ctypes.Structure):
        _fields_ = [('size', ctypes.c_ulong), ('data', ctypes.POINTER(ctypes.c_byte))]
    raw = base64.b64decode(text) if decrypt else text.encode('utf-8')
    buf = ctypes.create_string_buffer(raw)
    source = Blob(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))
    target = Blob()
    api = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not api(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise OSError('Не удалось открыть сохранённый пароль Windows. Введите его заново.')
    try:
        value = ctypes.string_at(target.data, target.size)
        return value.decode('utf-8') if decrypt else base64.b64encode(value).decode('ascii')
    finally:
        ctypes.windll.kernel32.LocalFree(ctypes.cast(target.data, ctypes.c_void_p))


def endpoint(url):
    parsed = urllib.parse.urlsplit(url.strip().rstrip('/'))
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        raise ValueError('Введите адрес сервера, например http://192.168.7.66:18765')
    return parsed


def request(settings, route, file=None):
    url = endpoint(settings['server'])
    cls = http.client.HTTPSConnection if url.scheme == 'https' else http.client.HTTPConnection
    conn = cls(url.hostname, url.port, timeout=20)
    password = protect(settings['secret'], decrypt=True)
    auth = base64.b64encode((settings['username']+':'+password).encode()).decode()
    headers = {'Authorization':'Basic '+auth, 'X-Local-App':'meeting-ai'}
    try:
        if file:
            file = Path(file)
            headers.update({'Content-Length':str(file.stat().st_size), 'Content-Type':'application/octet-stream',
                            'X-Filename':urllib.parse.quote(settings.get('name','Встреча')+file.suffix.lower())})
            conn.putrequest('POST', route)
            for key,value in headers.items(): conn.putheader(key,value)
            conn.endheaders()
            with file.open('rb') as stream:
                while block := stream.read(256*1024): conn.send(block)
            # The server hashes and snapshots the entire recording before replying.
            # A long recording on a slow disk may legitimately take hours here.
            conn.sock.settimeout(24 * 3600)
        else: conn.request('GET',route,headers=headers)
        response = conn.getresponse()
        body = response.read()
        if response.status == 401: raise ValueError('Сервер отклонил логин или пароль.')
        if response.status >= 300: raise ValueError(f'Сервер вернул ошибку {response.status}: '+body.decode('utf-8',errors='replace')[:250])
        return json.loads(body)
    finally: conn.close()


def enqueue(folder, settings, name):
    endpoint(settings['server'])
    item = dict(settings, name=name or 'Встреча', status='pending', error='', job_id=None)
    core.save(Path(folder)/'delivery.json',item)
    return {'local':str(folder)}


def deliver(folder, item):
    """An interrupted upload is retried; server content hashes deduplicate it."""
    folder = Path(folder)
    if not item.get('job_id'):
        reply = request(item,'/api/upload',folder/item.get('audio_file','meeting.wav'))
        if not re.fullmatch('[a-f0-9]{64}',reply.get('id','')): raise ValueError('Неверный ответ сервера.')
        item.update(job_id=reply['id'],status='processing',error='')
        core.save(folder/'delivery.json',item)
    reply = request(item,'/api/jobs/'+item['job_id'])
    item['server_status'] = reply['status']
    if reply['status'] == 'deleted':
        item.update(status='server_error',error='Запись находится в корзине сервера. Её можно восстановить в веб-интерфейсе.')
    elif reply['status'] == 'error':
        item.update(status='server_error',error=reply.get('error') or 'Ошибка обработки на сервере')
    elif reply['status'] in {'done','needs_review','needs_speaker_setup'}:
        if reply.get('summary') is not None:
            (folder/'Конспект.md').write_text(reply['summary'],encoding='utf-8')
            (folder/'Сводка.md').write_text(reply['summary'],encoding='utf-8')
        if reply.get('minutes') is not None:
            (folder/'Конспект.md').write_text(reply['minutes'],encoding='utf-8')
        if reply.get('transcript'):
            core.save(folder/'transcript.json',reply['transcript'])
            (folder/'Расшифровка.txt').write_text('\n'.join(core.transcript_lines(reply['transcript'])),encoding='utf-8')
        item.update(status='done',error='')
        if isinstance(reply.get('transcript'),dict) and not reply['transcript'].get('segments'):
            item.update(status='no_speech',error='Речь не обнаружена. Проверьте звук в исходной записи.')
    else: item.update(status='processing',error='')
    core.save(folder/'delivery.json',item)
    return item
