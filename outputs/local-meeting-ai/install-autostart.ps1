$ErrorActionPreference = 'Stop'
$startup = [Environment]::GetFolderPath('Startup')
$link = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $startup 'Meeting AI Server.lnk'))
$link.TargetPath = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\pythonw.exe'
$link.Arguments = '"' + (Join-Path $PSScriptRoot 'open_app.py') + '" --no-browser'
$link.WorkingDirectory = $PSScriptRoot
$link.Description = 'Meeting AI local server'
$link.Save()
Write-Host 'Server autostart installed for this Windows user.'
