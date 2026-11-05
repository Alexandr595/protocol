$startup = [Environment]::GetFolderPath('Startup')
Remove-Item -LiteralPath (Join-Path $startup 'Meeting AI Server.lnk') -ErrorAction SilentlyContinue
