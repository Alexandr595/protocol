"""Presentation only; the recorder and upload logic stay independent of Tk styling."""
import math
import tkinter as tk
from tkinter import ttk
from pathlib import Path
BG='#101a29'; PANEL='#1a293c'; TEXT='#eff6ff'; MUTED='#b3c5d8'; MINT='#65edd0'; BLUE='#97bbff'; RED='#ff917e'

class Signal(tk.Canvas):
    def __init__(self, parent, accent):
        super().__init__(parent,height=48,bg=PANEL,highlightthickness=0)
        self.accent=accent;self.history=[0.0]*44
        self.bind('<Configure>',lambda _:self.paint())
    def sample(self,peak):
        if peak<=0 and not any(self.history):return
        self.history=self.history[1:]+[min(1,max(0,math.log1p(max(0,peak)*40)/math.log(41)))]
        self.paint()
    def paint(self):
        self.delete('all')
        w=max(1,self.winfo_width());step=w/len(self.history)
        self.create_line(0,24,w,24,fill='#42556a')
        for i,v in enumerate(self.history):
            if v>.001:
                x=(i+.5)*step;h=1+v*21
                self.create_line(x,24-h,x,24+h,fill=self.accent,width=max(2,int(step*.55)),capstyle='round')

def draw_view(a):
    root=a.root
    root.iconbitmap(str(Path(__file__).with_name('protocol.ico')))
    root.configure(bg=BG);root.option_add('*Font','{Segoe UI} 10')
    st=ttk.Style();st.theme_use('clam')
    st.configure('.',background=BG,foreground=TEXT,font=('Segoe UI',10))
    st.configure('TButton',padding=(12,8),borderwidth=0,background='#30435a',foreground=TEXT)
    st.map('TButton',background=[('disabled','#202d3e'),('active','#405872')],foreground=[('disabled','#9aaabb')])
    for key,color in [('Start',MINT),('Stop',RED)]:
        st.configure(key+'.TButton',font=('Segoe UI',11,'bold'),background=color,foreground=BG)
        st.map(key+'.TButton',background=[('disabled','#202d3e'),('active','#dbf7f0'),('!disabled',color)],foreground=[('disabled','#94a9bc'),('!disabled',BG)])
    st.configure('TEntry',fieldbackground='#24364a',foreground=TEXT,insertcolor=TEXT,padding=6)
    st.configure('TCheckbutton',foreground=MUTED);st.map('TCheckbutton',background=[('active',BG)])
    c=tk.Canvas(root,bg=BG,highlightthickness=0);scroll=ttk.Scrollbar(root,command=c.yview)
    scroll.pack(side='right',fill='y');c.pack(side='left',fill='both',expand=True);c.configure(yscrollcommand=scroll.set)
    p=tk.Frame(c,bg=BG,padx=22,pady=14);win=c.create_window(0,0,anchor='nw',window=p)
    c.bind('<Configure>',lambda e:c.itemconfigure(win,width=e.width))
    p.bind('<Configure>',lambda _:c.configure(scrollregion=c.bbox('all')))
    root.bind('<MouseWheel>',lambda e:c.yview_scroll(-int(e.delta/120),'units'))
    def label(parent,text='',size=10,color=TEXT,bg=BG,bold=False,**kw):
        return tk.Label(parent,text=text,bg=bg,fg=color,font=('Segoe UI',size,'bold' if bold else 'normal'),anchor='w',justify='left',**kw)
    header=tk.Frame(p,bg=BG);header.pack(fill='x')
    label(header,'Протокол',25,bold=True).pack(side='left')
    a.badge=label(header,'●  ГОТОВ',10,MINT,bold=True);a.badge.pack(side='right')
    hero=tk.Frame(p,bg=PANEL,padx=16,pady=12);hero.pack(fill='x',pady=(10,8))
    label(hero,'Запись встречи',14,bg=PANEL,bold=True).pack(side='left')
    a.clock=label(hero,'00:00:00',19,MINT,PANEL,True);a.clock.pack(side='right')
    cards=tk.Frame(p,bg=BG);cards.pack(fill='x')
    a.levels=[]
    for i,(title,sub,col) in enumerate([('Комната','Микрофон',MINT),('Звонок','Звук компьютера',BLUE)]):
        cards.columnconfigure(i,weight=1,uniform='tracks')
        card=tk.Frame(cards,bg=PANEL,padx=12,pady=8);card.grid(row=0,column=i,sticky='ew',padx=(0,4) if not i else (4,0))
        label(card,title,13,col,PANEL,True).pack(anchor='w');label(card,sub,10,MUTED,PANEL).pack(anchor='w')
        meter=Signal(card,col);meter.pack(fill='x');a.levels.append(meter)
    row=tk.Frame(p,bg=BG);row.pack(fill='x',pady=(12,4))
    a.start_button=ttk.Button(row,text='●  Начать запись',style='Start.TButton',command=a.start);a.start_button.pack(side='left')
    a.stop_button=ttk.Button(row,text='■  Завершить и отправить',style='Stop.TButton',command=a.finish,state='disabled');a.stop_button.pack(side='left',padx=8)
    a.status=tk.StringVar(value='Подключите гарнитуру до начала записи.');label(p,textvariable=a.status,color=MUTED,wraplength=555).pack(fill='x',pady=4)
    a.mode=tk.BooleanVar();a.name=tk.StringVar()
    person=tk.Frame(p,bg=BG);label(person,'Имя сотрудника:').pack(side='left');ttk.Entry(person,textvariable=a.name).pack(side='left',fill='x',expand=True,padx=8)
    toggle=ttk.Checkbutton(p,text='Записать образец голоса',variable=a.mode,command=lambda:person.pack(after=toggle,fill='x') if a.mode.get() else person.pack_forget());toggle.pack(anchor='w',pady=4)
    a.server=tk.StringVar(value='http://192.168.7.66:18765');a.user=tk.StringVar(value='meeting');a.password=tk.StringVar()
    a.settings=tk.Frame(p,bg=PANEL,padx=12,pady=8);a.settings_open=True
    def switch():
        a.settings_open=not a.settings_open
        if a.settings_open:a.settings.pack(after=settings_toggle,fill='x')
        else:a.settings.pack_forget()
    settings_toggle=ttk.Button(p,text='Настройки подключения',command=switch);settings_toggle.pack(anchor='w',pady=(6,2))
    a.hide_settings=lambda:switch() if a.settings_open else None
    a.settings.pack(fill='x')
    for i,(name,v) in enumerate([('Сервер',a.server),('Логин',a.user),('Пароль',a.password)]):
        label(a.settings,name,bg=PANEL).grid(row=i,column=0,sticky='w',padx=(0,8));ttk.Entry(a.settings,textvariable=v,show='*' if i==2 else '').grid(row=i,column=1,sticky='ew',pady=2)
    a.settings.columnconfigure(1,weight=1)
    ttk.Button(a.settings,text='Сохранить подключение',command=a.configure).grid(row=3,column=1,sticky='e')
    a.connection=tk.StringVar(value='Проверяем подключение…');label(p,textvariable=a.connection,color=MUTED,wraplength=555).pack(fill='x',pady=6)
    footer=tk.Frame(p,bg=BG);footer.pack(fill='x',pady=4)
    import os,webbrowser
    ttk.Button(footer,text='Результаты',command=lambda:webbrowser.open(a.server.get())).pack(side='left')
    ttk.Button(footer,text='Папка записей',command=lambda:os.startfile(a.last_folder)).pack(side='left',padx=5)
    a.update_button=ttk.Button(footer,text='Проверить обновление',command=a.update_app);a.update_button.pack(side='right')
