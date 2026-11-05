"""Ask the server to stop safely; never kill an unrelated PID."""
import json
import urllib.request
import urllib.error
import ctypes
try:
    req=urllib.request.Request('http://127.0.0.1:18765/api/shutdown',data=b'{}',headers={'X-Local-App':'meeting-ai'})
    try:
        with urllib.request.urlopen(req,timeout=10) as response:json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(json.load(exc).get('error','Сервер не остановлен.')) from exc
except Exception as exc:
    ctypes.windll.user32.MessageBoxW(None,str(exc),'Остановка сервера',0x10)
