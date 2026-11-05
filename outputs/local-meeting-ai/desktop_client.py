"""Portable Windows recorder: local sources, durable outbox, central processing."""
import json
import os
from pathlib import Path
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox
import meeting_ai as core
from recording import Recorder
from native_audio import WindowsAudio as NativeAudio
from client_transfer import protect, endpoint, request, enqueue, deliver

DATA = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'MeetingAIClient'
if os.environ.get('MEETING_CLIENT_DATA'): DATA = Path(os.environ['MEETING_CLIENT_DATA'])
DATA.mkdir(parents=True,exist_ok=True)
core.ROOT = DATA
core.database().close()


class ClientRecorder(Recorder):
    delivery_settings = None
    def __init__(self):
        super().__init__(audio_backend=NativeAudio)
    def _publish(self,folder,metadata):
        return enqueue(folder,self.delivery_settings,metadata['name'])


def paste_entry(entry):
    """Explicit paste also works when Tk's Ctrl+V binding misses Cyrillic V."""
    if entry.instate(['disabled']) or entry.instate(['readonly']): return 'break'
    try:
        value=entry.clipboard_get()
    except tk.TclError:
        entry.bell();return 'break'
    # Credentials are single-line. Do not strip spaces from a password.
    value=value.replace('\r','').replace('\n','')
    if entry.selection_present():entry.delete(tk.SEL_FIRST,tk.SEL_LAST)
    entry.insert(tk.INSERT,value)
    return 'break'


def entry_shortcut(event):
    # Windows virtual-key codes do not change with keyboard layout.
    if event.keycode==86:return paste_entry(event.widget)
    if event.keycode==65:
        event.widget.selection_range(0,tk.END)
        return 'break'


class App:
    def __init__(self, window):
        self.window=window;window.title('Протокол — клиент записи 0.4.0-preview · WASAPI');window.geometry('940x740')
        self.starting=False
        self.rec=ClientRecorder();self.devices=[];self.closed=threading.Event();self.lock=threading.RLock();self.transfer_lock=threading.Lock();self.messages=[]
        self.settings_file=DATA/'state/client.json'
        try: cfg=json.loads(self.settings_file.read_text(encoding='utf-8'))
        except (OSError,ValueError): cfg={}
        self.server=tk.StringVar(value=cfg.get('server','http://192.168.7.66:18765'))
        self.user=tk.StringVar(value=cfg.get('username','meeting'));self.password=tk.StringVar()
        try: self.password.set(protect(cfg['secret'],decrypt=True))
        except (KeyError,OSError): pass
        self.name=tk.StringVar();self.notice=tk.StringVar(value='Записываются микрофон и звук ЭТОГО компьютера. Обработка — на сервере.')
        self.status=tk.StringVar(value='Готов к записи');self.device_vars=[tk.StringVar(),tk.StringVar()]
        box=ttk.Frame(window,padding=16);box.pack(fill='both',expand=True)
        for row,(title,var,hidden) in enumerate([('Адрес сервера',self.server,False),('Логин',self.user,False),('Пароль',self.password,True),('Название встречи',self.name,False)]):
            ttk.Label(box,text=title).grid(row=row,column=0,sticky='w',pady=4)
            field=ttk.Frame(box);field.grid(row=row,column=1,columnspan=3,sticky='ew')
            entry=ttk.Entry(field,textvariable=var,show='*' if hidden else '')
            entry.pack(side='left',fill='x',expand=True)
            entry.bind('<Control-KeyPress>',entry_shortcut)
            entry.bind('<Shift-Insert>',lambda event:paste_entry(event.widget))
            menu=tk.Menu(entry,tearoff=False)
            menu.add_command(label='Вставить',command=lambda e=entry:paste_entry(e))
            menu.add_command(label='Выделить всё',command=lambda e=entry:e.selection_range(0,tk.END))
            def popup(event,m=menu):
                try:m.tk_popup(event.x_root,event.y_root)
                finally:m.grab_release()
                return 'break'
            entry.bind('<Button-3>',popup)
            if hidden:ttk.Button(field,text='Вставить',command=lambda e=entry:paste_entry(e)).pack(side='right',padx=(8,0))
        self.combos=[]
        for row,title in enumerate(['Микрофон этого компьютера','Звук этого компьютера'],4):
            ttk.Label(box,text=title).grid(row=row,column=0,sticky='w',pady=4)
            combo=ttk.Combobox(box,textvariable=self.device_vars[row-4],state='readonly');combo.grid(row=row,column=1,columnspan=3,sticky='ew');self.combos.append(combo)
        self.refresh_button=ttk.Button(box,text='Обновить устройства',command=self.refresh_devices);self.refresh_button.grid(row=6,column=0,pady=12)
        ttk.Button(box,text='Проверить связь / сохранить',command=self.connect).grid(row=6,column=1)
        self.start_button=ttk.Button(box,text='● Начать запись',command=self.start);self.start_button.grid(row=6,column=2)
        self.stop_button=ttk.Button(box,text='■ Завершить',command=self.stop);self.stop_button.grid(row=6,column=3)
        ttk.Label(box,textvariable=self.status,font=('Segoe UI',13,'bold')).grid(row=7,column=0,columnspan=4,sticky='w',pady=8)
        ttk.Label(box,textvariable=self.notice,wraplength=870).grid(row=8,column=0,columnspan=4,sticky='w')
        self.tree=ttk.Treeview(box,columns=('name','status'),show='headings',height=10)
        self.tree.heading('name',text='Мои записи на этом устройстве');self.tree.heading('status',text='Состояние')
        self.tree.column('name',width=450);self.tree.column('status',width=350)
        self.tree.grid(row=9,column=0,columnspan=4,sticky='nsew',pady=12)
        ttk.Button(box,text='Открыть файлы / результат',command=self.open_files).grid(row=10,column=0)
        ttk.Button(box,text='Повторить / новые данные входа',command=self.retry).grid(row=10,column=1)
        ttk.Button(box,text='Восстановить запись',command=self.recover).grid(row=10,column=2)
        ttk.Button(box,text='Папка всех записей',command=lambda:os.startfile(DATA)).grid(row=10,column=3)
        ttk.Button(box,text='Скопировать ошибку',command=self.copy_error).grid(row=11,column=0,sticky='w',pady=(12,0))
        ttk.Button(box,text='Сбросить ошибку',command=self.reset_error).grid(row=11,column=1,sticky='w',pady=(12,0))
        box.columnconfigure(1,weight=1);box.rowconfigure(9,weight=1)
        self.refresh_devices();window.protocol('WM_DELETE_WINDOW',self.close)
        threading.Thread(target=self.worker,daemon=True).start();self.tick()

    def settings(self):
        server=self.server.get().strip().rstrip('/');endpoint(server)
        if not self.password.get() or not self.user.get().strip(): raise ValueError('Введите логин и пароль сервера.')
        result={'server':server,'username':self.user.get().strip(),'secret':protect(self.password.get())}
        core.save(self.settings_file,result);return result

    def copy_error(self):
        r=self.rec.snapshot()
        lines=['Протокол, клиент 0.4.0-preview WASAPI',r.get('error') or self.notice.get(),
               'Микрофон: '+self.device_vars[0].get(),
               'Звук компьютера: '+self.device_vars[1].get()]
        # Deliberately exclude credentials, server address and recording names.
        self.window.clipboard_clear();self.window.clipboard_append('\n'.join(lines))
        messagebox.showinfo('Ошибка скопирована','Вставьте этот текст в сообщение. Пароль и данные входа не копируются.')

    def reset_error(self):
        try:
            self.rec.reset();self.notice.set('Ошибка сброшена. Обновите устройства и повторите выбор источников.')
        except Exception as exc:self.notice.set(str(exc))

    def run(self,fn):
        def task():
            try: fn()
            except Exception as exc:
                with self.lock:self.messages.append(str(exc))
        threading.Thread(target=task,daemon=True).start()

    def connect(self):
        try: cfg=self.settings()
        except Exception as exc: self.notice.set(str(exc));return
        def check():
            reply=request(cfg,'/api/state')
            if 'models' not in reply:raise ValueError('По этому адресу нет сервера Протокол.')
            with self.lock:self.messages.append('Связь с сервером установлена. Данные входа сохранены.')
        self.run(check)

    def refresh_devices(self):
        try:
            self.devices=self.rec.devices()
            for kind,combo,var in zip(['mic','system'],self.combos,self.device_vars):
                ds=[d for d in self.devices if d['kind']==kind];values=['Не записывать']+[f"{d['id']}: {d['name']}" for d in ds]
                previous=var.get();combo['values']=values
                default=next((d for d in ds if d.get('default')),ds[0] if ds else None)
                var.set(previous if previous in values else f"{default['id']}: {default['name']}" if default else values[0])
        except Exception as exc:self.notice.set(str(exc))

    def start(self):
        try:
            if self.starting or self.rec.busy():raise ValueError('Дождитесь завершения текущей записи.')
            cfg=self.settings();ids=[int(v.get().split(':',1)[0]) if ':' in v.get() else None for v in self.device_vars]
            self.rec.delivery_settings=cfg;name=self.name.get()
            # Disable immediately; no simultaneous startup threads.
            self.start_button['state']='disabled'
            self.starting=True
            self.notice.set('Подключение к устройствам Windows…')
            def begin():
                try:self.rec.start(ids[0],'meeting',name,ids[1])
                finally:self.starting=False
            self.run(begin)
        except Exception as exc:self.notice.set(str(exc))

    def stop(self):
        try:self.rec.stop()
        except Exception as exc:self.notice.set(str(exc))

    def selected(self):
        ids=self.tree.selection()
        if not ids:raise ValueError('Выберите запись в списке.')
        return DATA/'recordings'/ids[0]

    def open_files(self):
        try:os.startfile(self.selected())
        except Exception as exc:self.notice.set(str(exc))

    def retry(self):
        try:
            folder=self.selected();cfg=self.settings()
            def update():
                with self.transfer_lock:
                    item=json.loads((folder/'delivery.json').read_text(encoding='utf-8'))
                    if item['server']!=cfg['server']:raise ValueError('Адрес отличается от сервера этой записи. Верните прежний адрес для повтора.')
                    item.update(username=cfg['username'],secret=cfg['secret'],error='',status='processing' if item.get('job_id') else 'pending')
                    core.save(folder/'delivery.json',item)
                with self.lock:self.messages.append('Данные входа обновлены. Повтор — в течение 15 секунд. Ошибку обработки повторите в веб-интерфейсе сервера.')
            self.run(update)
        except Exception as exc:self.notice.set(str(exc))

    def recover(self):
        try:
            if self.rec.busy():raise ValueError('Дождитесь завершения текущей записи.')
            folder=self.selected();self.rec.delivery_settings=self.settings();self.rec.recover(folder.name)
        except Exception as exc:self.notice.set(str(exc))

    def worker(self):
        while not self.closed.is_set():
            if not self.rec.busy():
                for file in sorted((DATA/'recordings').glob('*/delivery.json')):
                    if self.closed.is_set() or self.rec.busy():break
                    with self.transfer_lock:
                        item=None
                        try:
                            item=json.loads(file.read_text(encoding='utf-8'))
                            if item['status']=='done':continue
                            if not item.get('job_id'):
                                item.update(status='sending',error='');core.save(file,item)
                            deliver(file.parent,item)
                        except Exception as exc:
                            if item is not None:
                                item['error']=str(exc);core.save(file,item)
            self.closed.wait(15)

    def tick(self):
        if self.starting:
            self.start_button['state']='disabled';self.stop_button['state']='disabled';self.refresh_button['state']='disabled'
            for combo in self.combos:combo['state']='disabled'
            self.status.set('Подключаем источники…')
            self.window.after(500,self.tick)
            return
        r=self.rec.snapshot();busy=self.rec.busy()
        self.start_button['state']='disabled' if busy else 'normal';self.stop_button['state']='normal' if r['status']=='recording' else 'disabled'
        self.refresh_button['state']='disabled' if busy else 'normal'
        for combo in self.combos:combo['state']='disabled' if busy else 'readonly'
        label={'idle':'Готов к записи','recording':'● ЗАПИСЬ','saving':'Сохраняем','complete':'Сохранено','error':'Ошибка'}.get(r['status'],r['status'])
        seconds=int(r['seconds']);self.status.set(f"{label}  {seconds//60:02}:{seconds%60:02}  Микрофон: {r['levels']['mic']:.0%}  Компьютер: {r['levels']['system']:.0%}")
        if r['error']:self.notice.set(r['error'])
        elif r['warning']:self.notice.set(r['warning'])
        elif r['status']=='recording':self.notice.set('Запись идёт. Проверьте оба индикатора звука.')
        # Never block the GUI while the transfer thread holds its lock.
        if self.lock.acquire(blocking=False):
            try:
                if self.messages:self.notice.set(self.messages.pop(0))
                selected=self.tree.selection();self.tree.delete(*self.tree.get_children())
                labels={'pending':'Ожидает отправки','sending':'Отправляется на сервер','processing':'Обрабатывается на сервере','done':'Результат сохранён','server_error':'Ошибка на сервере'}
                for file in sorted((DATA/'recordings').glob('*/session.json'),reverse=True):
                    try:
                        meta=json.loads(file.read_text(encoding='utf-8'));delivery=file.parent/'delivery.json'
                        item=json.loads(delivery.read_text(encoding='utf-8')) if delivery.exists() else {}
                        label=item.get('error') or labels.get(item.get('status'),'Запись / сохранение' if busy and self.rec.path and file.parent==self.rec.path.parent else 'Незавершённая запись')
                        self.tree.insert('', 'end',iid=file.parent.name,values=(meta['name'],label))
                    except (OSError,ValueError):continue
                for ident in selected:
                    if self.tree.exists(ident):self.tree.selection_add(ident)
            finally:self.lock.release()
        self.window.after(500,self.tick)

    def close(self):
        if self.starting or self.rec.busy():messagebox.showinfo('Идёт запись','Сначала завершите запись и дождитесь сохранения.');return
        self.closed.set();self.window.destroy()


if __name__=='__main__':
    import ctypes
    ctypes.windll.kernel32.CreateMutexW.restype=ctypes.c_void_p
    mutex=ctypes.windll.kernel32.CreateMutexW(None,False,'Local\\MeetingAIClient')
    if ctypes.windll.kernel32.GetLastError()==183:raise SystemExit('Клиент уже запущен.')
    root=tk.Tk();App(root);root.mainloop()
