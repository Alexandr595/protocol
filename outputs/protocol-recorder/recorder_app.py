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
        self.root=tk.Tk();self.root.title('Протокол · 0.10.2');self.root.geometry('800x740');self.root.minsize(650,520)
        self.events=queue.Queue();self.session=None;self.busy=False;self.queue_busy=False;self.last_folder=STORE
        from recorder_view import draw_view
        draw_view(self)
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
    def apply_settings(self,s):
        self.server.set(s['server']);self.user.set(s['username'])
        if s.get('configured'):self.hide_settings()
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
        active=bool(session and not self.busy)
        self.badge.config(text=('●  ЗАПИСЬ' if active else ('●  ПОДОЖДИТЕ' if self.busy else '●  ГОТОВ')),fg='#ff917e' if active else '#65edd0')
        for i,meter in enumerate(self.levels):
            src=session.sources[i] if active and i<len(session.sources) else None
            meter.sample(src.peak if src and time.monotonic()-session.epoch-getattr(src,'last',-100)<1 else 0)
        if active:
            elapsed=time.monotonic()-session.epoch
            silent=[('Комната' if s.kind=='microphone' else 'Звонок') for s in session.sources if s.max_peak<.0001]
            hint=('Пока нет сигнала: '+', '.join(silent)) if silent else 'Звук получен со всех источников.'
            self.status.set(f'● Запись {int(elapsed)//60:02}:{int(elapsed)%60:02}   {hint}')
            seconds=int(elapsed);self.clock.config(text=f'{seconds//3600:02}:{seconds//60%60:02}:{seconds%60:02}')
            if any(s.error for s in session.sources) or (session.voice and elapsed>=40):self.finish()
        self.root.after(100,self.tick)
    def close(self):
        if self.session or self.busy:messagebox.showinfo('Протокол','Сначала завершите запись или сохранение.');return
        self.root.destroy()
    def main(self):self.root.mainloop()
if __name__=='__main__':App().main()

