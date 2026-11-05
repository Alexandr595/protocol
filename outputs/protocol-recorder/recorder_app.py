"""Employee UI. Capture uses fresh workers; delivery retains existing encrypted settings."""
import os,queue,threading,time,tkinter as tk,webbrowser
from pathlib import Path
from tkinter import ttk,messagebox
from portable_session import Session,bridge
HOME=Path(os.environ.get('PROTOCOL_DATA_DIR',str(Path(os.environ['LOCALAPPDATA'])/'Protocol')))
STORE=HOME/'Recordings';STORE.mkdir(parents=True,exist_ok=True)
VOICES=HOME/'VoiceSamples';VOICES.mkdir(exist_ok=True)

class App:
    def __init__(self):
        self.root=tk.Tk();self.root.title('Протокол · 0.10.0');self.root.geometry('800x740');self.root.minsize(650,520)
        self.events=queue.Queue();self.session=None;self.busy=False;self.queue_busy=False;self.last_folder=STORE
        canvas=tk.Canvas(self.root,highlightthickness=0)
        scroll=ttk.Scrollbar(self.root,orient='vertical',command=canvas.yview)
        scroll.pack(side='right',fill='y');canvas.pack(side='left',fill='both',expand=True)
        canvas.configure(yscrollcommand=scroll.set)
        p=ttk.Frame(canvas,padding=20);content=canvas.create_window((0,0),window=p,anchor='nw')
        p.bind('<Configure>',lambda event:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',lambda event:canvas.itemconfigure(content,width=event.width))
        ttk.Label(p,text='Протокол',font=('Segoe UI',24,'bold')).pack(anchor='w')
        ttk.Label(p,text='Микрофон и звук звонка → запись → результат на сервере').pack(anchor='w',pady=(0,12))
        settings=ttk.LabelFrame(p,text='Подключение к серверу',padding=10);settings.pack(fill='x')
        self.server=tk.StringVar(value='http://192.168.7.66:18765');self.user=tk.StringVar(value='meeting');self.password=tk.StringVar()
        for label,var,secret in [('Сервер',self.server,False),('Логин',self.user,False),('Пароль',self.password,True)]:
            row=ttk.Frame(settings);row.pack(fill='x',pady=2);ttk.Label(row,text=label,width=10).pack(side='left');ttk.Entry(row,textvariable=var,show='*' if secret else '').pack(side='left',fill='x',expand=True)
        ttk.Button(settings,text='Сохранить подключение',command=self.configure).pack(anchor='e',pady=4)
        self.connection=tk.StringVar(value='Проверяем сохранённый вход…');ttk.Label(p,textvariable=self.connection,wraplength=710).pack(anchor='w',pady=8)
        self.mode=tk.BooleanVar();ttk.Checkbutton(p,text='Добавить образец голоса (только микрофон)',variable=self.mode).pack(anchor='w')
        self.name=tk.StringVar();ttk.Label(p,text='Для образца голоса укажите имя и фамилию:').pack(anchor='w');ttk.Entry(p,textvariable=self.name).pack(fill='x',pady=(2,10))
        self.levels=[]
        for text in ['Комната · микрофон Windows','Звонок · звук компьютера Windows']:
            ttk.Label(p,text=text).pack(anchor='w');bar=ttk.Progressbar(p,maximum=1);bar.pack(fill='x',pady=(3,8));self.levels.append(bar)
        row=ttk.Frame(p);row.pack(fill='x',pady=8)
        self.start_button=ttk.Button(row,text='● Начать запись',command=self.start);self.start_button.pack(side='left')
        self.stop_button=ttk.Button(row,text='■ Завершить и отправить',command=self.finish,state='disabled');self.stop_button.pack(side='left',padx=8)
        ttk.Button(row,text='Результаты',command=lambda:webbrowser.open(self.server.get())).pack(side='right')
        self.status=tk.StringVar(value='Устройства выбираются автоматически при начале записи.');ttk.Label(p,textvariable=self.status,wraplength=710).pack(anchor='w',pady=8)
        footer=ttk.Frame(p);footer.pack(fill='x')
        ttk.Button(footer,text='Папка записей',command=lambda:os.startfile(self.last_folder)).pack(side='left')
        self.update_button=ttk.Button(footer,text='Проверить обновление',command=self.update_app);self.update_button.pack(side='right')
        self.root.protocol('WM_DELETE_WINDOW',self.close)
        self.run(self.restore,lambda value:self.connection.set(value));self.root.after(100,self.tick);self.root.after(2000,self.send_queue)
    def run(self,fn,done):
        def work():
            try:self.events.put((done,fn(),None))
            except Exception as ex:self.events.put((done,None,str(ex)))
        threading.Thread(target=work,daemon=True).start()
    def restore(self):
        settings=bridge(op='settings');self.events.put((self.apply_settings,settings,None))
        return bridge(op='check') if settings['configured'] else 'Укажите сервер и сохраните подключение. Запись сохраняется и без сети.'
    def apply_settings(self,s):self.server.set(s['server']);self.user.set(s['username'])
    def update_app(self):
        if self.busy or self.session:return
        self.busy=True;self.status.set('Проверяем подписанное обновление…')
        def check():
            try:return bridge(op='update')
            finally:self.busy=False
        self.run(check,self.status.set)
    def configure(self):
        data=dict(op='configure',server=self.server.get(),username=self.user.get(),password=self.password.get())
        self.run(lambda:bridge(**data),lambda result:(self.connection.set(result),self.password.set('')))
    def start(self):
        if self.busy or self.session:return
        voice=self.mode.get();name=self.name.get().strip()
        if voice and len(name)<2:self.status.set('Укажите имя и фамилию для образца голоса.');return
        self.busy=True;self.start_button.config(state='disabled');self.status.set('Открываем источники записи…')
        session=Session(VOICES if voice else STORE,voice);session.person=name;self.session=session;self.last_folder=session.folder
        def begin():
            try:session.start();return True
            except Exception:
                self.session=None;raise
            finally:self.busy=False
        self.run(begin,lambda result:self.stop_button.config(state='normal'))
    def finish(self):
        if self.busy or not self.session:return
        self.busy=True;self.stop_button.config(state='disabled');session=self.session
        self.status.set('Сохраняем запись…')
        def finish():
            try:
                session.finish();self.session=None
                errors=[s.error for s in session.sources if s.error]
                missing=[s.kind for s in session.sources if not s.bytes or s.max_peak<.0001]
                if session.voice:
                    if errors or missing:raise RuntimeError('Образец не записан: '+'; '.join(errors+missing))
                    return bridge(op='voice',file=str(session.voice_file()),name=session.person)
                if any(s.bytes and s.max_peak>=.0001 for s in session.sources):bridge(op='enqueue',folder=str(session.folder))
                if errors or missing:return 'Запись неполная: '+'; '.join(errors+missing)+'. Сохранённые дорожки не удалены.'
                return 'Запись сохранена и поставлена в очередь отправки.'
            finally:self.busy=False
        self.run(finish,lambda result:self.status.set(result))
    def send_queue(self):
        if not self.queue_busy:
            self.queue_busy=True
            def send():
                try:return bridge(op='queue',storage=str(STORE))
                finally:self.queue_busy=False
            self.run(send,lambda result:self.connection.set(result) if result else None)
        self.root.after(30000,self.send_queue)
    def tick(self):
        while not self.events.empty():
            fn,result,error=self.events.get()
            if error:self.status.set(error)
            else:fn(result)
        idle=not self.session and not self.busy
        for btn in [self.start_button,self.update_button]:btn.config(state='normal' if idle else 'disabled')
        session=self.session
        if session and not self.busy:
            elapsed=time.monotonic()-session.epoch
            silent=[('Комната' if s.kind=='microphone' else 'Звонок') for s in session.sources if s.max_peak<.0001]
            hint=('Пока нет сигнала: '+', '.join(silent)) if silent else 'Звук получен со всех источников.'
            self.status.set(f'● Запись {int(elapsed)//60:02}:{int(elapsed)%60:02}   {hint}')
            for i,source in enumerate(session.sources):
                self.levels[i]['value']=source.peak if time.monotonic()-session.epoch-getattr(source,'last',-100)<1 else 0
            if any(s.error for s in session.sources) or (session.voice and elapsed>=40):self.finish()
        self.root.after(100,self.tick)
    def close(self):
        if self.session or self.busy:messagebox.showinfo('Протокол','Сначала завершите запись или сохранение.');return
        self.root.destroy()
    def main(self):self.root.mainloop()
if __name__=='__main__':App().main()

