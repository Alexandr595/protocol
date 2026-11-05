$ErrorActionPreference = 'Stop'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run enable-lan.cmd as administrator.'
}
$ruleName = 'LocalMeetingAI-LAN-18765'
if (-not (Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -Name $ruleName -DisplayName 'Meeting AI - local network' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 18765 -RemoteAddress 192.168.7.0/24 -Profile Any -ErrorAction Stop | Out-Null
}
Write-Host 'LAN access enabled: http://192.168.7.66:18765/'
