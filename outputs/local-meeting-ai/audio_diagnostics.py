"""Opt-in endpoint probe. Discards audio; never reads client credentials."""
import ctypes
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import threading
import time


def probe(mode):
    def run():
        initialized = False
        backend = None
        try:
            if mode == 'worker-com':
                result = ctypes.windll.ole32.CoInitializeEx(None, 0)
                print('CoInitializeEx:', hex(result & 0xffffffff), flush=True)
                initialized = result in (0, 1)
            from windows_audio import WindowsAudio
            backend = WindowsAudio()
            devices = backend.devices()
            print('Endpoints:', json.dumps(devices, ensure_ascii=False), flush=True)
            for device in devices:
                stream = None
                counts = [0]
                def discard(data, frames, times, flags):
                    counts[0] += frames
                print('Opening:', device['name'], flush=True)
                try:
                    stream = backend.open(device, discard)
                    stream.start_stream()
                    time.sleep(.3)
                    print('SUCCESS; active:', stream.is_active(), 'frames:', counts[0], flush=True)
                except Exception as exc:
                    print('FAILED:', repr(exc), flush=True)
                finally:
                    if stream is not None:
                        stream.close()
        except Exception as exc:
            print('PROBE FAILED:', repr(exc), flush=True)
        finally:
            if backend is not None:
                backend.close()
            if initialized:
                ctypes.windll.ole32.CoUninitialize()
    if mode == 'main':
        run()
    else:
        thread = threading.Thread(target=run)
        thread.start()
        thread.join()


def main():
    if len(sys.argv) == 2:
        probe(sys.argv[1])
        return
    lines = ['Audio diagnostics v1', platform.platform(), sys.version,
             'No audio files or credentials are collected.']
    try:
        import winreg
        for hive, name in ((winreg.HKEY_CURRENT_USER, 'HKCU'), (winreg.HKEY_LOCAL_MACHINE, 'HKLM')):
            for suffix in ('', '\\NonPackaged'):
                try:
                    with winreg.OpenKey(hive, r'Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone' + suffix) as key:
                        lines.append(name + suffix + ': ' + str(winreg.QueryValueEx(key, 'Value')[0]))
                except OSError:
                    lines.append(name + suffix + ': value not available')
    except ImportError:
        pass
    for mode in ('main', 'worker', 'worker-com'):
        print('Checking:', mode, flush=True)
        lines.append('\nMODE: ' + mode)
        try:
            result = subprocess.run([sys.executable, '-u', str(Path(__file__).resolve()), mode],
                                    capture_output=True, timeout=45,
                                    env={**os.environ, 'PYTHONUTF8': '1'})
            lines.append(result.stdout.decode('utf-8', errors='replace'))
            lines.append(result.stderr.decode('utf-8', errors='replace'))
            lines.append('Exit code: ' + str(result.returncode))
        except subprocess.TimeoutExpired as exc:
            lines.append('TIMEOUT\n' + (exc.stdout or b'').decode('utf-8', errors='replace'))
    folder = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'MeetingAIClient'
    folder.mkdir(parents=True, exist_ok=True)
    report = folder / 'audio-diagnostics.txt'
    report.write_text('\n'.join(lines), encoding='utf-8')
    print('Report:', report)
    if sys.platform == 'win32':
        os.startfile(str(report))


if __name__ == '__main__':
    main()
