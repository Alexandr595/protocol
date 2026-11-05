"""One capture session, independent sources, durable journals, explicit finalization."""
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
import numpy as np
import meeting_ai as core
from windows_audio import WindowsAudio
from session_audio import assemble

BUSY = {'recording', 'saving', 'enrolling'}


class Recorder:
    def __init__(self, audio_backend=None):
        self.audio_backend = audio_backend or WindowsAudio
        self.lock = threading.RLock()
        self.thread = None
        self.status = 'idle'
        self.error = self.warning = self.name = ''
        self.purpose = 'meeting'
        self.result = self.path = None
        self.duration = 0
        self.levels = {'mic': 0, 'system': 0}
        self.origin = None
        self.cached_devices = []
        self.metadata = None
        self.signal_peaks = {}

    def busy(self):
        return bool(self.thread and self.thread.is_alive())

    def devices(self):
        with self.lock:
            if self.busy(): return self.cached_devices
            backend = self.audio_backend()
            try: self.cached_devices = backend.devices()
            finally: backend.close()
            return self.cached_devices

    def settings(self):
        try: return json.loads((core.ROOT / 'state/recording-settings.json').read_text(encoding='utf-8'))
        except (OSError, ValueError): return {}

    def snapshot(self):
        with self.lock:
            seconds = time.perf_counter() - self.origin if self.status == 'recording' and self.origin else self.duration
            warning = self.warning
            silent = [k for k,v in self.signal_peaks.items() if v < .0001]
            if self.status == 'recording' and seconds > 10 and silent:
                warning = 'Пока нет слышимого сигнала: ' + ', '.join('комната' if k=='mic' else 'компьютер' for k in silent) + '. Проверьте источник и громкость.'
            return {'status': self.status, 'error': self.error, 'warning': warning,
                    'seconds': round(seconds, 1), 'level': max(self.levels.values()),
                    'levels': dict(self.levels), 'purpose': self.purpose, 'name': self.name,
                    'result': self.result, 'file': str(self.path) if self.path else None}

    def start(self, device=None, purpose='meeting', name='', system_device=None):
        with self.lock:
            if self.busy(): raise ValueError('Сначала завершите текущую запись или сохранение голоса.')
            if purpose not in {'meeting', 'voice'}: raise ValueError('Неизвестный тип записи.')
            name = ' '.join(str(name).split())
            if purpose == 'voice' and not 2 <= len(name) <= 100: raise ValueError('Введите имя сотрудника.')
            if purpose == 'voice': system_device = None
            core.database().close()
            self.metadata = None
            self.path = None
            backend = self.audio_backend()
            streams = []
            try:
                previous_devices = self.cached_devices
                self.cached_devices = backend.devices()
                selected = []
                for kind, index in [('mic', device), ('system', system_device)]:
                    if index is None: continue
                    found = next((d for d in self.cached_devices if d['kind'] == kind and d['id'] == index and type(index) is int), None)
                    if not found: raise ValueError('Выбранное устройство недоступно. Обновите список устройств.')
                    previous = next((d for d in previous_devices if d['id'] == index), None)
                    if previous and (previous.get('native_id', previous['name']), previous['kind']) != (found.get('native_id', found['name']), found['kind']):
                        raise ValueError('Список устройств изменился. Нажмите «Обновить устройства» и выберите источники заново.')
                    selected.append(found)
                if not selected: raise ValueError('Выберите микрофон или звук компьютера. Микрофон может быть не подключён.')
                if purpose == 'voice' and not any(d['kind'] == 'mic' for d in selected):
                    raise ValueError('Для образца голоса нужен микрофон.')
                if shutil.disk_usage(core.ROOT).free < 2 * 1024**3:
                    raise ValueError('Для записи и подготовки результата нужно хотя бы 2 ГБ свободного места.')
                self.chunks = queue.Queue(maxsize=512)
                self.stop_event = threading.Event()
                self.levels = {'mic': 0, 'system': 0}
                self.last_callback = {}
                self.track_frames = {d['kind']: 0 for d in selected}
                self.signal_peaks = {d['kind']: 0 for d in selected}
                self.error = self.warning = ''
                self.result = None
                self.duration = 0
                self.purpose, self.name = purpose, name
                label = re.sub(r'[^\w .-]', '_', name or 'Разговор')[:60].strip(' .') or 'Разговор'
                folder = core.ROOT / 'recordings' / (time.strftime('%Y-%m-%d_%H-%M-%S') + '_' + label + '_' + uuid.uuid4().hex[:6])
                self.path = folder / 'meeting.wav'
                self.metadata = {'version': 1, 'name': name or 'Разговор', 'purpose': purpose,
                                 'started': time.time(), 'status': 'recording', 'duration': 0,
                                 'tracks': selected, 'warning': '', 'error': ''}
                backend.close()
                backend = None
                ready = threading.Event()
                self.status = 'saving'
                self.thread = threading.Thread(target=self._capture, args=(folder, selected, ready), daemon=True)
                self.thread.start()
                if not ready.wait(20):
                    self.stop_event.set()
                    raise RuntimeError('Устройство долго не отвечает. Дождитесь завершения и обновите устройства.')
                if self.status == 'error': raise RuntimeError(self.error)
                preferences = {
                    'mic_name': next((d['name'] for d in selected if d['kind'] == 'mic'), None),
                    'system_name': next((d['name'] for d in selected if d['kind'] == 'system'), None),
                    'mic_id': device, 'system_id': system_device}
                if purpose == 'meeting': core.save(core.ROOT / 'state/recording-settings.json', preferences)
                return self.snapshot()
            except Exception as exc:
                for stream in streams:
                    try: stream.close()
                    except Exception: pass
                if backend: backend.close()
                self.status = 'error'; self.error = str(exc)
                if self.metadata and self.path and self.path.parent.exists():
                    self.metadata.update(status='error', error=self.error)
                    core.save(self.path.parent / 'session.json', self.metadata)
                elif not self.busy():
                    self.path = None
                raise

    def _capture(self, folder, selected, ready):
        # PortAudio/COM creation, stream lifetime and teardown belong to one thread.
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
        backend = None
        streams = []
        source = None
        try:
            backend = self.audio_backend()
            inventory = backend.devices()
            # A new PortAudio instance may assign different indices. Never open
            # an unrelated endpoint merely because it inherited the old index.
            for source in selected:
                matches = [d for d in inventory if (d.get('native_id', d['name']), d['kind']) == (source.get('native_id', source['name']), source['kind'])]
                match = next((d for d in matches if d['id'] == source['id']), None)
                if match is None and len(matches) == 1: match = matches[0]
                if match is None: raise ValueError('Устройство отключено или изменилось. Обновите устройства и повторите выбор.')
                source.update(match)
            self.origin = time.perf_counter()
            for source in selected:
                stream = backend.open(source, self._callback(source))
                streams.append(stream)
                stream.start_stream()
                if source.get('backend'):
                    self.warning = 'Микрофон подключён через резервный драйвер: '+source['backend']+'.'
            if self.stop_event.is_set(): raise RuntimeError('Запуск записи отменён по тайм-ауту.')
            folder.mkdir(parents=True)
            core.save(folder / 'session.json', self.metadata)
            self.status = 'recording'
        except Exception as exc:
            self.status = 'error'
            label = ('Микрофон' if source['kind'] == 'mic' else 'Звук компьютера') + ' «' + source['name'] + '»' if source else 'Аудиоустройство'
            self.error = f'{label}: {exc}'
            if isinstance(exc, OSError):
                self.error += '. Обновите устройства и проверьте выбранный источник в настройках звука Windows.'
                if (any('hands-free' in d['name'].lower() for d in selected)
                        and any(d['kind'] == 'system' and 'stereo' in d['name'].lower() for d in selected)):
                    self.error += ' Для Bluetooth-гарнитуры с включённым микрофоном используйте выход Hands-Free, а не Stereo, в Windows, звонке и здесь.'
            for stream in streams:
                try: stream.close()
                except Exception: pass
            if backend: backend.close()
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
            ready.set()
            return
        ready.set()
        try: self._write(backend, streams, folder)
        finally: ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)

    def _callback(self, source):
        kind, rate, channels = source['kind'], source['rate'], source['channels']
        anchor = None
        def receive(data, frames, times, flags):
            nonlocal anchor
            now = time.perf_counter()
            self.last_callback[kind] = now
            if flags: self.warning = 'Устройство сообщило о пропуске звука. Проверьте запись.'
            pcm = np.frombuffer(data, dtype='<i2')
            self.levels[kind] = float(np.max(np.abs(pcm.astype(np.int32)))) / 32768 if len(pcm) else 0
            self.signal_peaks[kind] = max(self.signal_peaks[kind],self.levels[kind])
            current, adc = times.get('current_time', 0), times.get('input_buffer_adc_time', 0)
            if current and adc and 0 <= current - adc < 2:
                # Map each device clock to the shared monotonic timeline once.
                if anchor is None: anchor = now - self.origin - current
                elapsed = anchor + adc
            else:
                elapsed = now - self.origin - frames / rate
                self.warning = 'Нет точных меток устройства; синхронизация источников приблизительная.'
            try: self.chunks.put_nowait((kind, bytes(data), max(0., elapsed), len(data) // (2 * channels)))
            except queue.Full:
                self.error = 'Диск не успевает сохранять звук. Частичная запись сохранена.'
                self.stop_event.set()
        return receive

    def stop(self):
        with self.lock:
            if self.status != 'recording': raise ValueError('Сейчас запись не идёт.')
            self.duration = time.perf_counter() - self.origin
            self.status = 'saving'
            self.stop_event.set()
            return self.snapshot()

    def _write(self, backend, streams, folder):
        files = {}; journals = {}
        try:
            for source in self.metadata['tracks']:
                kind = source['kind']
                files[kind] = (folder / (kind + '.pcm')).open('wb')
                journals[kind] = (folder / (kind + '.jsonl')).open('w', encoding='utf-8')
            def persist(item):
                kind, raw, elapsed, frames = item
                offset = files[kind].tell()
                files[kind].write(raw)
                journals[kind].write(json.dumps({'time': elapsed, 'frames': frames, 'offset': offset}) + '\n')
                self.track_frames[kind] += frames
            last_flush = time.monotonic()
            while not self.stop_event.is_set():
                try: persist(self.chunks.get(timeout=.2))
                except queue.Empty: pass
                elapsed = time.perf_counter() - self.origin
                if self.purpose == 'voice' and elapsed >= 90:
                    self.warning = 'Образец голоса сохранён: записано 90 секунд.'
                    self.stop_event.set()
                for stream in streams:
                    if getattr(stream, 'warning', ''):
                        self.warning = stream.warning
                    if not stream.is_active():
                        raise RuntimeError(getattr(stream, 'error', '') or 'Аудиоустройство отключилось. Частичная запись сохранена.')
                if time.monotonic() - last_flush >= 2:
                    reserve = elapsed * 16000 * 2 * (2 * len(self.metadata['tracks']) + 2) + 256 * 1024**2
                    if shutil.disk_usage(folder).free < reserve:
                        raise RuntimeError('Заканчивается место на диске. Исходники сохранены.')
                    self.metadata['duration'] = elapsed
                    core.save(folder / 'session.json', self.metadata)
                    for f in [*files.values(), *journals.values()]: f.flush(); os.fsync(f.fileno())
                    last_flush = time.monotonic()
            self.duration = max(self.duration, time.perf_counter() - self.origin)
            self.status = 'saving'
            for stream in streams:
                stream.stop_stream()
                if getattr(stream, 'error', ''): self.error = stream.error
            while not self.chunks.empty(): persist(self.chunks.get_nowait())
            for f in [*files.values(), *journals.values()]: f.flush(); os.fsync(f.fileno()); f.close()
            if self.error: raise RuntimeError(self.error)
            self.metadata.update(status='saving', duration=self.duration, warning=self.warning)
            core.save(folder / 'session.json', self.metadata)
            self.path = assemble(folder, self.metadata)
            if not any(self.track_frames.values()): raise ValueError('Устройства не передали звук. Проверьте выбранные источники.')
            if self.purpose == 'voice':
                self.status = 'enrolling'
                self.result = self.enroll_file(self.path, self.name)
            else:
                self.result = self._publish(folder, self.metadata)
            self.metadata.update(status='complete', result=self.result)
            core.save(folder / 'session.json', self.metadata)
            self.status = 'complete'
        except Exception as exc:
            self.duration = time.perf_counter() - self.origin
            self.error = str(exc); self.status = 'error'
            self.metadata.update(status='error', duration=self.duration, error=self.error)
            core.save(folder / 'session.json', self.metadata)
        finally:
            for stream in streams:
                try: stream.close()
                except Exception: pass
            backend.close()
            for f in [*files.values(), *journals.values()]:
                if not f.closed: f.close()
            self.levels = {'mic': 0, 'system': 0}

    def _publish(self, folder, metadata):
        key = core.add(folder / 'meeting.wav')
        with core.database() as db:
            db.execute("UPDATE jobs SET name=? WHERE id=? AND name='meeting.wav'", (folder.name + '.wav', key))
        core.save(core.ROOT / 'inbox' / (key + '.capture.json'), {'session': str(folder), 'tracks': metadata['tracks'], 'warning': metadata.get('warning', '')})
        return {'job_id': key}

    def reset(self):
        with self.lock:
            if self.busy(): raise ValueError('Дождитесь завершения текущей записи.')
            self.status = 'idle'; self.error = self.warning = ''; self.result = self.path = None
            self.metadata = None; self.duration = 0; self.origin = None
            self.levels = {'mic': 0, 'system': 0}
            return self.snapshot()

    def dismiss(self, session):
        with self.lock:
            if self.busy(): raise ValueError('Дождитесь завершения текущей записи.')
            if session not in {r['id'] for r in self.recoverable()}:
                raise ValueError('Незавершённая запись не найдена.')
            file = core.ROOT / 'recordings' / session / 'session.json'
            data = json.loads(file.read_text(encoding='utf-8'))
            data['dismissed'] = True
            core.save(file, data)
            if self.path and self.path.parent == file.parent: self.reset()
            return {'dismissed': session}

    def recoverable(self):
        result = []
        for file in sorted((core.ROOT / 'recordings').glob('*/session.json'), reverse=True):
            if self.busy() and self.path and file.parent == self.path.parent: continue
            try:
                data = json.loads(file.read_text(encoding='utf-8'))
                if data['purpose'] == 'meeting' and data['status'] != 'complete' and not data.get('dismissed'):
                    has_audio = any(p.stat().st_size > 0 for p in file.parent.glob('*.pcm'))
                    result.append({'id': file.parent.name, 'name': data['name'], 'seconds': round(data.get('duration', 0)), 'error': data.get('error', ''), 'can_recover': has_audio and data.get('duration', 0) >= 1})
            except (OSError, ValueError, KeyError): continue
        return result

    def recover(self, session):
        with self.lock:
            if self.busy(): raise ValueError('Дождитесь завершения текущей записи.')
            if session not in {r['id'] for r in self.recoverable() if r['can_recover']}: raise ValueError('Нет аудио для восстановления или запись короче секунды.')
            folder = core.ROOT / 'recordings' / session
            self.metadata = json.loads((folder / 'session.json').read_text(encoding='utf-8'))
            self.path = folder / 'meeting.wav'; self.name = self.metadata['name']; self.purpose = 'meeting'
            self.status = 'saving'; self.error = ''; self.result = None; self.duration = self.metadata.get('duration', 0)
            def task():
                try:
                    assemble(folder, self.metadata)
                    self.result = self._publish(folder, self.metadata)
                    self.metadata.update(status='complete', result=self.result)
                    core.save(folder / 'session.json', self.metadata)
                    self.status = 'complete'
                except Exception as exc: self.status = 'error'; self.error = str(exc)
            self.thread = threading.Thread(target=task, daemon=True); self.thread.start()
            return self.snapshot()

    def enroll_file(self, path, name):
        destination = core.ROOT / 'state' / ('enrollment-' + uuid.uuid4().hex + '.json')
        process = subprocess.run([sys.executable, str(Path(__file__).with_name('speakers.py')), 'enroll', str(path), name, str(destination)], capture_output=True, text=True, encoding='utf-8', creationflags=subprocess.CREATE_NO_WINDOW)
        if process.returncode: raise ValueError(process.stderr.strip()[-1500:] or 'Не удалось сохранить голос.')
        try: return json.loads(destination.read_text(encoding='utf-8'))
        finally: destination.unlink(missing_ok=True)

    def import_voice(self, path, name):
        with self.lock:
            if self.busy(): raise ValueError('Дождитесь окончания записи или сохранения голоса.')
            self.name = name; self.purpose = 'voice'; self.path = Path(path); self.status = 'enrolling'
            self.error = self.warning = ''; self.duration = 0; self.result = None
            def task():
                try: self.result = self.enroll_file(path, name); self.status = 'complete'
                except Exception as exc: self.error = str(exc); self.status = 'error'
            self.thread = threading.Thread(target=task, daemon=True); self.thread.start()
            return self.snapshot()
