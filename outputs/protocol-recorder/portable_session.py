"""Durable PCM recording, using isolated capture workers; no UI dependencies."""
import base64,json,os,subprocess,threading,time,uuid,wave
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def save(path,data):
    tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8');os.replace(tmp,path)

def bridge(**request):
    p=subprocess.run([str(ROOT/'DeliveryBridge.exe')],input=json.dumps(request,ensure_ascii=True),text=True,encoding='utf-8',stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
    result=json.loads(p.stdout)
    if not result['ok']:raise RuntimeError(result['error'])
    return result['result']

class Source:
    def __init__(self,folder,kind,epoch,system_mic=True):
        self.folder,self.kind,self.epoch=folder,kind,epoch
        self.segments=[];self.bytes=0;self.peak=0;self.max_peak=0;self.error='';self.name='';self.format=None
        self.ready=threading.Event();self.closed=threading.Event();self.writer=None;self.part_bytes=0;self.start=0;self.first=0;self.on_update=None
        command=[str(ROOT/'audio-runtime/python.exe'),'-u','-c',"import runpy;runpy.run_path('capture_worker.py',run_name='__main__')"]
        if kind=='microphone' and system_mic:command=[str(ROOT/'WindowsMic.exe')]
        self.proc=subprocess.Popen(command,cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',creationflags=subprocess.CREATE_NO_WINDOW)
        self.proc.stdin.write(json.dumps({'source':kind,'name':None})+'\n');self.proc.stdin.flush()
        threading.Thread(target=self.read,daemon=True).start()
    def close_part(self):
        if not self.writer:return
        self.writer.close();self.writer=None
        final=self.partial.with_name(self.partial.name.replace('.partial',''));os.replace(self.partial,final)
        rate,ch,bits=self.format
        self.segments.append(dict(file=final.name,firstPacketSeconds=self.first,startSeconds=self.start,audioSeconds=self.part_bytes/(rate*ch*(bits//8)),bytes=self.part_bytes))
        if self.on_update:self.on_update()
    def read(self):
        normal=False
        try:
            for line in self.proc.stdout:
                item=json.loads(line)
                if item['type']=='ready':
                    self.input_float=item['floating']
                    self.format=(item['rate'],item['channels'],16);self.name=item['name'];self.ready.set()
                elif item['type']=='audio':
                    data=base64.b64decode(item['data'])
                    if self.input_float:
                        import array,math
                        data=array.array('h',(max(-32768,min(32767,int(v*32768))) if math.isfinite(v) else 0 for v in array.array('f',data))).tobytes()
                    rate,ch,bits=self.format;now=time.monotonic()-self.epoch
                    if self.writer and (self.part_bytes>=rate*ch*2*60 or now-self.last>.5):self.close_part()
                    if not self.writer:
                        self.partial=self.folder/f'{self.kind}-{len(self.segments)+1:04}.partial.wav'
                        self.writer=wave.open(str(self.partial),'wb');self.writer.setparams((ch,2,rate,0,'NONE','not compressed'));self.part_bytes=0;self.first=now;self.start=max(0,now-len(data)/(rate*ch*2))
                    self.writer.writeframes(data);self.writer._file.flush()
                    self.part_bytes+=len(data);self.bytes+=len(data);self.last=now
                    import array
                    values=array.array('h',data);self.peak=max((abs(v) for v in values),default=0)/32768;self.max_peak=max(self.max_peak,self.peak)
                elif item['type']=='error':raise RuntimeError(item['message'])
                elif item['type']=='stopped':normal=True;break
            if not normal:raise RuntimeError('Аудиодвижок завершился неожиданно.')
        except Exception as ex:self.error=str(ex)
        finally:
            try:self.close_part()
            except Exception as ex:self.error=str(ex)
            self.ready.set();self.closed.set()
    def stop(self):
        try:self.proc.stdin.write('stop\n');self.proc.stdin.flush()
        except (OSError,ValueError):pass
    def join(self):
        if not self.closed.wait(8):
            self.error='Источник не остановился вовремя.';self.proc.kill();self.closed.wait(3)
        try:self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:self.proc.kill();self.proc.wait(timeout=3)
        self.proc.stdin.close();self.proc.stdout.close()
    def snapshot(self):
        return dict(source=self.kind,device=self.name,bytes=self.bytes,maxPeak=self.max_peak,error=self.error,segments=self.segments)

class Session:
    def __init__(self,storage,voice=False):
        self.folder=Path(storage)/(time.strftime('%Y-%m-%d_%H-%M-%S')+'_'+uuid.uuid4().hex[:6]);self.folder.mkdir(parents=True)
        self.epoch=time.monotonic();self.sources=[];self.voice=voice;self.journal_lock=threading.Lock()
    def start(self):
        try:
            for kind in (['microphone'] if self.voice else ['microphone','computer']):
                attempts=[]
                for system_mic in ([True,False] if kind=='microphone' else [False]):
                    source=Source(self.folder,kind,self.epoch,system_mic)
                    if source.ready.wait(15) and not source.error:
                        self.sources.append(source);source.on_update=lambda:self.save("recording");break
                    attempts.append(source.error or 'Источник не ответил вовремя.')
                    source.stop();source.join()
                else:
                    label='Микрофон' if kind=='microphone' else 'Звук компьютера'
                    raise RuntimeError(label+' не открылся: '+'; '.join(attempts))
            self.save('recording')
        except Exception:
            self.finish();raise
    def save(self,status):
        with self.journal_lock:save(self.folder/'session.json',dict(version='0.10.0',status=status,elapsedSeconds=time.monotonic()-self.epoch,sources=[s.snapshot() for s in self.sources]))
    def finish(self):
        for s in self.sources:s.stop()
        for s in self.sources:s.join()
        self.save('capture_error' if not self.sources or any(s.error or not s.bytes or s.max_peak<.0001 for s in self.sources) else 'stopped')
    def voice_file(self):
        dest=self.folder/'voice.wav'
        with wave.open(str(dest),'wb') as out:
            for part in self.sources[0].segments:
                with wave.open(str(self.folder/part['file']),'rb') as src:
                    if out.getnframes()==0:out.setparams(src.getparams())
                    while data:=src.readframes(65536):out.writeframes(data)
        return dest

