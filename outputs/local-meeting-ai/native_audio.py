"""Bounded PCM transport from the isolated Windows Core Audio host."""
import hashlib
import json
import math
from pathlib import Path
import struct
import subprocess
import threading
import numpy as np

HOST = Path(__file__).resolve().parent / 'native' / 'AudioHost.exe'
HEADER = struct.Struct('<iddii')
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def read_exact(pipe, size):
    result = bytearray()
    while len(result) < size:
        chunk = pipe.read(size - len(result))
        if not chunk:
            if not result:
                return None
            raise EOFError('Захват завершился посреди аудиопакета.')
        result.extend(chunk)
    return bytes(result)


def read_packet(pipe, channels):
    header = read_exact(pipe, HEADER.size)
    if header is None:
        return None
    length, adc, current, flags, rate = HEADER.unpack(header)
    if not 0 < length <= 4 * 1024 * 1024 or length % (2 * channels):
        raise ValueError('Повреждён аудиопакет WASAPI.')
    if not math.isfinite(adc) or not math.isfinite(current):
        raise ValueError('Некорректные метки времени WASAPI.')
    if not 8000 <= rate <= 384000:
        raise ValueError('Некорректная частота WASAPI.')
    data = read_exact(pipe, length)
    if data is None:
        raise EOFError('Захват завершился до получения звука.')
    return data, length // (2 * channels), {'current_time': current, 'input_buffer_adc_time': adc}, flags, rate


class PcmConverter:
    """Keep the journal format stable across changes of the Windows mix rate."""
    def __init__(self, channels):
        self.channels = channels
        self.rate = self.input_count = self.output_count = 0
        self.previous = None

    def convert(self, data, frames, times, flags, rate):
        if rate != self.rate or flags & 1:
            self.rate, self.input_count, self.output_count, self.previous = rate, 0, 0, None
        if rate == 48000:
            return data, frames, times, flags
        samples = np.frombuffer(data, dtype='<i2').reshape(-1, self.channels)
        end = self.input_count + frames
        # Integer arithmetic prevents cumulative duration drift on hour-long captures.
        output_end = (end * 48000 + rate - 1) // rate
        positions = np.arange(self.output_count, output_end, dtype=np.float64) * rate / 48000 - self.input_count
        if self.previous is not None:
            samples = np.vstack([self.previous, samples])
            xp = np.arange(-1, frames)
        else:
            xp = np.arange(frames)
        result = np.column_stack([np.interp(positions, xp, samples[:, ch]) for ch in range(self.channels)])
        self.previous = samples[-1:].copy()
        self.input_count, self.output_count = end, output_end
        if len(positions) and times['input_buffer_adc_time']:
            times = dict(times, input_buffer_adc_time=times['input_buffer_adc_time'] + positions[0] / rate)
        return result.astype('<i2').tobytes(), len(result), times, flags


class NativeStream:
    def __init__(self, device, callback):
        self.device, self.callback = device, callback
        self.process = None
        self.ready = threading.Event()
        self.error = self.warning = ''
        self.started = self.stopping = False
        self.readers = []

    def _status(self):
        try:
            for line in self.process.stderr:
                event = json.loads(line.decode('utf-8-sig'))
                kind, message = event['type'], event['message']
                if kind == 'ready':
                    self.started = True
                    self.ready.set()
                elif kind == 'error':
                    self.error = message
                    self.ready.set()
                elif kind == 'warning':
                    self.warning = message
                elif kind == 'resumed':
                    self.warning = 'Источник переподключён: ' + message + '. В записи возможен перерыв.'
        except Exception as exc:
            self.error = 'Ошибка обмена с WASAPI: ' + str(exc)
        finally:
            self.ready.set()

    def _audio(self):
        converter = PcmConverter(self.device['channels'])
        try:
            while True:
                packet = read_packet(self.process.stdout, self.device['channels'])
                if packet is None:
                    break
                converted = converter.convert(*packet)
                if converted[1]: self.callback(*converted)
        except Exception as exc:
            self.error = str(exc)

    def start_stream(self):
        if self.process is not None:
            raise RuntimeError('Захват уже запущен.')
        self.process = subprocess.Popen([str(HOST), 'capture', self.device['kind'], self.device['native_id']],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NO_WINDOW)
        for target in (self._status, self._audio):
            thread = threading.Thread(target=target, daemon=True)
            self.readers.append(thread)
            thread.start()
        if not self.ready.wait(8) or not self.started or self.error:
            message = self.error or 'Windows не подтвердила запуск источника за 8 секунд.'
            self.close()
            raise RuntimeError(message)

    def is_active(self):
        return self.process is not None and self.process.poll() is None and not self.error

    def stop_stream(self):
        if self.process is None or self.stopping:
            return
        self.stopping = True
        if self.process.poll() is None:
            try:
                self.process.stdin.write(b'STOP\n')
                self.process.stdin.flush()
            except (OSError, ValueError):
                pass
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
                self.error = self.error or 'Аудиодрайвер не завершился вовремя; сохранён полученный звук.'
        for thread in self.readers:
            thread.join(timeout=3)

    def close(self):
        self.stop_stream()
        if self.process is not None:
            for pipe in (self.process.stdin, self.process.stdout, self.process.stderr):
                pipe.close()


class WindowsAudio:
    """Recorder-compatible backend; endpoint IDs never depend on enumeration order."""
    def __init__(self):
        if not HOST.is_file():
            raise RuntimeError('Не найден native/AudioHost.exe. Распакуйте клиент целиком.')

    def devices(self):
        result = subprocess.run([str(HOST), 'list'], capture_output=True, timeout=8, creationflags=NO_WINDOW)
        if result.returncode:
            try:
                message = json.loads(result.stderr.decode('utf-8-sig').splitlines()[-1])['message']
            except (ValueError, IndexError, KeyError):
                message = 'Не удалось получить устройства Windows Core Audio.'
            raise RuntimeError(message)
        devices = json.loads(result.stdout.decode('utf-8-sig'))
        seen = set()
        for device in devices:
            key = device['kind'] + ':' + device['native_id']
            device['id'] = (-1 if device['kind'] == 'mic' else -2) if device['automatic'] else int(hashlib.sha256(key.encode()).hexdigest()[:12], 16)
            if device['id'] in seen:
                raise RuntimeError('Неоднозначный идентификатор аудиоустройства.')
            seen.add(device['id'])
            device.update(rate=48000, channels=1 if device['kind'] == 'mic' else 2, default=device['automatic'])
        return devices

    def open(self, device, callback):
        return NativeStream(device, callback)

    def close(self):
        pass
