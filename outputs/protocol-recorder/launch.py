"""Visible startup errors, including failures before the main window exists."""
import ctypes, os, runpy, traceback
from pathlib import Path

try:
    runpy.run_path(str(Path(__file__).with_name('recorder_app.py')),run_name='__main__')
except Exception:
    details=traceback.format_exc()
    location=''
    for base in [Path(os.environ.get('LOCALAPPDATA','.'))/'Protocol',Path(os.environ.get('TEMP','.'))]:
        try:
            base.mkdir(parents=True,exist_ok=True)
            path=base/'startup.log';path.write_text(details,encoding='utf-8');location=str(path);break
        except OSError:pass
    ctypes.windll.user32.MessageBoxW(None,'Не удалось открыть Протокол.\n'+details.splitlines()[-1]+'\n\n'+location,'Протокол',16)
