"""Portable capture worker. Device indexes never cross the process boundary."""
import base64,json,sys,threading,time,subprocess
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'audio-packages'))
import pyaudiowpatch as pa

def emit(kind,**values):
    print(json.dumps(dict(type=kind,**values),ensure_ascii=True),flush=True)

def select_device(audio,kind,name):
    host=audio.get_host_api_info_by_type(pa.paWASAPI)
    if not name:
        if kind=='computer':
            # A USB or Bluetooth call may use a different Windows communications
            # endpoint from music playback. Match only an unambiguous loopback.
            try:
                proc=subprocess.run([str(Path(__file__).with_name('WindowsMic.exe')),'--call-output'],
                    capture_output=True,timeout=4,creationflags=subprocess.CREATE_NO_WINDOW)
                if not proc.returncode:
                    return select_device(audio,kind,json.loads(proc.stdout)['name'])
            except (OSError,ValueError,RuntimeError,subprocess.TimeoutExpired):pass
            return audio.get_default_wasapi_loopback()
        index=host['defaultInputDevice']
        if index<0: raise RuntimeError('В Windows нет доступного микрофона.')
        return audio.get_device_info_by_index(index)
    def clean(s):return s.removesuffix(' [Loopback]').strip().casefold()
    devices=[audio.get_device_info_by_index(i) for i in range(audio.get_device_count())]
    matches=[d for d in devices if d['hostApi']==host['index'] and d['maxInputChannels']>0
             and bool(d.get('isLoopbackDevice'))==(kind=='computer') and clean(d['name'])==clean(name)]
    if len(matches)!=1:raise RuntimeError('Выбранный источник изменился или недоступен: '+name)
    return matches[0]

def main():
    cfg=json.loads(sys.stdin.readline());stop=threading.Event()
    def commands():
        # EOF means the owning client has closed; never leave a hidden recorder running.
        sys.stdin.readline();stop.set()
    threading.Thread(target=commands,daemon=True).start()
    stream=None
    try:
        with pa.PyAudio() as audio:
            d=select_device(audio,cfg['source'],cfg.get('name'))
            rate=int(d['defaultSampleRate']);channels=int(d['maxInputChannels'])
            errors=[]
            for fmt,bits,floating in [(pa.paInt16,16,False),(pa.paFloat32,32,True)]:
                try:
                    stream=audio.open(format=fmt,channels=channels,rate=rate,input=True,
                        input_device_index=d['index'],frames_per_buffer=1024,start=False)
                    stream.start_stream();break
                except Exception as ex:
                    errors.append(str(ex))
                    if stream:stream.close();stream=None
            if stream is None:raise RuntimeError('Не удалось открыть '+d['name']+': '+'; '.join(errors))
            emit('ready',name=d['name'],rate=rate,channels=channels,bits=bits,floating=floating)
            try:
                while not stop.is_set():
                    available=stream.get_read_available()
                    if available:
                        # Bound pipe messages; overflow is an error, never silently drop audio.
                        data=stream.read(min(available,4096),exception_on_overflow=True)
                        emit('audio',data=base64.b64encode(data).decode('ascii'))
                    else:stop.wait(.01)
            finally:
                stream.stop_stream();stream.close();stream=None
    except Exception as ex:
        emit('error',message=type(ex).__name__+': '+str(ex))
    finally:emit('stopped')

if __name__=='__main__':main()
