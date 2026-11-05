param([ValidateSet('add','run','watch','status','retry')][string]$Action = 'run', [string]$AudioPath)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$workspaceRoot = Split-Path (Split-Path $projectRoot -Parent) -Parent
$pythonPath = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$env:PYTHONPATH = Join-Path $workspaceRoot 'work\runtime\packages'
$env:PYTHONUTF8 = '1'
$env:HF_HUB_OFFLINE = '1'
$env:HF_HUB_DISABLE_TELEMETRY = '1'
if ($AudioPath) {
    & $pythonPath (Join-Path $projectRoot 'meeting_ai.py') $Action $AudioPath
} else {
    & $pythonPath (Join-Path $projectRoot 'meeting_ai.py') $Action
}
if ($LASTEXITCODE -ne 0) { throw "Операция завершилась с ошибкой $LASTEXITCODE" }
