"""Small local server controller. Never terminates processes by PID."""
import json
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
URL = 'http://127.0.0.1:18765'
PREFS = ROOT / 'state/control-panel.json'


def request(path, post=False):
    req = urllib.request.Request(URL + path, data=b'{}' if post else None,
                                 headers={'X-Local-App': 'meeting-ai'})
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=3) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(json.load(exc).get('error', str(exc))) from exc


def snapshot():
    try:
        data = request('/api/state')
        return data if 'models' in data and 'jobs' in data else None
    except (OSError, ValueError, RuntimeError):
        return None


class Control:
    def __init__(self, window):
        self.window = window
        self.commands = queue.Queue()
        self.events = queue.Queue()
        self.closed = threading.Event()
        self.pending = False
        try:
            self.resume = json.loads(PREFS.read_text(encoding='utf-8')).get('resume_queue', False)
        except (OSError, ValueError):
            self.resume = False
        window.title('Протокол — управление сервером')
        window.geometry('590x330')
        window.minsize(540, 330)
        window.configure(bg='#0d1920')
        tk.Label(window, text='Протокол', font=('Segoe UI', 25, 'bold'), bg='#0d1920', fg='#eaf5f1').pack(anchor='w', padx=28, pady=(22, 4))
        tk.Label(window, text='Управление на серверном компьютере', font=('Segoe UI', 11), bg='#0d1920', fg='#b4cac4').pack(anchor='w', padx=30)
        self.status = tk.StringVar(value='Проверяем состояние…')
        tk.Label(window, textvariable=self.status, font=('Segoe UI', 12), bg='#0d1920', fg='#8de0c8', wraplength=510, justify='left', height=4).pack(fill='x', padx=28, pady=12)
        row = tk.Frame(window, bg='#0d1920'); row.pack(fill='x', padx=28)
        self.start = tk.Button(row, text='▶ Запустить', command=lambda: self.send('start'), bg='#8de0c8', fg='#142d29', relief='flat', font=('Segoe UI', 11), padx=16, pady=10, state='disabled')
        self.start.pack(side='left', padx=(0, 8))
        self.stop = tk.Button(row, text='■ Остановить', command=self.stop_click, bg='#344a50', fg='white', relief='flat', font=('Segoe UI', 11), padx=16, pady=10, state='disabled')
        self.stop.pack(side='left', padx=(0, 8))
        tk.Button(row, text='Открыть сайт', command=lambda: webbrowser.open(URL), bg='#344a50', fg='white', relief='flat', font=('Segoe UI', 11), padx=14, pady=10).pack(side='left')
        tk.Label(window, text='Закрытие этого окна не выключает сервер.', bg='#0d1920', fg='#b4cac4', font=('Segoe UI', 10)).pack(anchor='w', padx=28, pady=(20, 0))
        window.protocol('WM_DELETE_WINDOW', self.close)
        threading.Thread(target=self.worker, daemon=True).start()
        self.drain()

    def close(self):
        if self.pending and not messagebox.askyesno('Остановка ещё ожидается', 'Если закрыть окно, отложенная остановка будет отменена, очередь останется на паузе. Закрыть?', parent=self.window):
            return
        self.closed.set(); self.window.destroy()

    def send(self, action):
        self.start.config(state='disabled'); self.stop.config(state='disabled')
        self.status.set('Выполняем действие…'); self.commands.put(action)

    def stop_click(self):
        if messagebox.askyesno('Остановить сервер?', 'Убедитесь, что сотрудники завершили браузерные записи и отправили их. После остановки сайт будет недоступен. Текущая обработка завершится перед выключением.', parent=self.window):
            self.send('stop')

    def remember(self):
        PREFS.parent.mkdir(exist_ok=True)
        PREFS.write_text(json.dumps({'resume_queue': self.resume}), encoding='utf-8')

    def worker(self):
        pending = False
        error = ''
        while not self.closed.is_set():
            try:
                try: action = self.commands.get(timeout=2)
                except queue.Empty: action = None
                if self.closed.is_set(): return
                state = snapshot()
                if action:
                    error = ''
                    if action == 'start':
                        pending = False
                        if not state:
                            subprocess.run([sys.executable, str(ROOT/'open_app.py'), '--no-browser'], cwd=ROOT, creationflags=subprocess.CREATE_NO_WINDOW, timeout=30, check=True)
                            state = snapshot()
                            if not state: raise RuntimeError('Сервер не запустился. Подробности: state/interface.log.')
                        if self.resume: request('/api/start', True)
                    elif action == 'stop' and state:
                        if state.get('recording', {}).get('status') in {'recording', 'saving', 'enrolling'}:
                            raise RuntimeError('Сначала завершите запись или добавление голоса на сервере.')
                        self.resume = bool((state.get('folder') or {}).get('processing_enabled'))
                        self.remember()
                        request('/api/pause', True); pending = True
                if pending:
                    state = snapshot()
                    if not state: pending = False
                    elif not state.get('worker') and not any(j['status']=='running' for j in state['jobs']):
                        request('/api/shutdown', True)
                state = snapshot()
                if not state: pending = False
                self.events.put((state, pending, error))
            except Exception as exc:
                pending = False; error = str(exc)
                self.events.put((snapshot(), pending, error))

    def drain(self):
        try:
            while True:
                state, self.pending, error = self.events.get_nowait()
                if error: text = error
                elif self.pending: text = 'Остановка запрошена. Ждём завершения обработки.\n«Отменить остановку» вернёт сервер к работе.'
                elif state:
                    running = next((j['name'] for j in state['jobs'] if j['status']=='running'), None)
                    text = '● Сервер работает' + ('\nОбрабатывается: '+running if running else '\nСайт доступен.')
                else: text = '○ Сервер выключен или не отвечает'
                self.status.set(text)
                self.start.config(text='Отменить остановку' if self.pending else '▶ Запустить', state='normal' if self.pending or not state else 'disabled')
                self.stop.config(state='normal' if state and not self.pending else 'disabled')
        except queue.Empty: pass
        self.window.after(200, self.drain)


if __name__ == '__main__':
    window = tk.Tk(); Control(window); window.mainloop()
