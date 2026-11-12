"""Foreground entry point for Windows Task Scheduler, before interactive sign-in."""
import os
from pathlib import Path
import subprocess
import sys

project = Path(__file__).resolve().parent
state = project / 'state'
state.mkdir(exist_ok=True)
env = dict(os.environ, PYTHONPATH=str(project.parents[1] / 'work/runtime/packages'),
           PYTHONUTF8='1', HF_HUB_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1')
with (state / 'interface.log').open('ab') as log:
    server = subprocess.run(
        [sys.executable, '-u', '-c', "import runpy; runpy.run_module('web_server', run_name='__main__')"],
        cwd=project, env=env, stdout=log, stderr=log,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
sys.exit(server.returncode)
