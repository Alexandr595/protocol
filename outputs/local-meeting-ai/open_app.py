"""Double-click launcher: starts this local app once, then opens the browser."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import webbrowser

root = Path(__file__).resolve().parent
url = 'http://127.0.0.1:18765'


def alive():
    try:
        with urllib.request.urlopen(url + '/api/state', timeout=2) as response:
            data = json.load(response)
        return 'models' in data and 'jobs' in data
    except (OSError, ValueError):
        return False


if not alive():
    (root / 'state').mkdir(exist_ok=True)
    env = os.environ.copy()
    env['PYTHONPATH'] = str(root.parents[1] / 'work/runtime/packages')
    env['PYTHONUTF8'] = '1'
    with (root / 'state/interface.log').open('ab') as log:
        # This runtime returns paInvalidDevice for direct script startup (and
        # for -m web_server). The runpy bootstrap is verified through the HTTP
        # recording API, including in a hidden child process.
        proc = subprocess.Popen([sys.executable, '-c',
            "import runpy; runpy.run_module('web_server', run_name='__main__')"], cwd=root,
            env=env, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
    for _ in range(40):
        if alive():
            break
        if proc.poll() is not None:
            break
        time.sleep(.25)
if alive():
    if '--no-browser' not in sys.argv: webbrowser.open(url)
else:
    import ctypes
    ctypes.windll.user32.MessageBoxW(None, 'Не удалось запустить интерфейс. Подробности в state/interface.log.', 'Протокол', 0x10)
