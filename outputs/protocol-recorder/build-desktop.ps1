param([Parameter(Mandatory=$true)][string]$SigningKey,[string]$Dist="$PSScriptRoot/../local-meeting-ai/dist")
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Security
Add-Type -AssemblyName System.IO.Compression.FileSystem
$fx="$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319"
$rsa=[Security.Cryptography.RSACryptoServiceProvider]::new(3072)
$rsa.PersistKeyInCsp=$false
if(Test-Path -LiteralPath $SigningKey){
 $private=[Security.Cryptography.ProtectedData]::Unprotect([IO.File]::ReadAllBytes($SigningKey),$null,'CurrentUser')
 $rsa.FromXmlString([Text.Encoding]::UTF8.GetString($private))
}else{
 $private=[Text.Encoding]::UTF8.GetBytes($rsa.ToXmlString($true))
 [IO.File]::WriteAllBytes($SigningKey,[Security.Cryptography.ProtectedData]::Protect($private,$null,'CurrentUser'))
}
[IO.File]::WriteAllText("$PSScriptRoot/update-public.xml",$rsa.ToXmlString($false))
& "$PSScriptRoot/build-mic.ps1"
Push-Location $PSScriptRoot
try{
 & "$fx/csc.exe" /nologo /target:winexe /win32icon:protocol.ico /out:Protocol.exe /reference:System.Windows.Forms.dll DesktopLauncher.cs
 if($LASTEXITCODE){throw 'Launcher build failed'}
 & "$fx/csc.exe" /nologo /out:DeliveryBridge.exe /reference:System.Web.Extensions.dll /reference:System.Security.dll /reference:System.IO.Compression.dll /reference:System.IO.Compression.FileSystem.dll Delivery.cs DeliveryBridge.cs UpdateClient.cs
 if($LASTEXITCODE){throw 'Bridge build failed'}
 New-Item -ItemType Directory -Path $Dist -Force | Out-Null
 $env:PROTOCOL_DIST=[IO.Path]::GetFullPath($Dist)
 & ./audio-runtime/python.exe desktop_msi.py "$Dist/ProtocolSetup.msi"
 if($LASTEXITCODE){throw 'Payload build failed'}
 New-Item -ItemType Directory -Path $Dist -Force | Out-Null
 if($LASTEXITCODE){throw 'Installer build failed'}
 $hash=(Get-FileHash "$Dist/ProtocolSetup.msi" -Algorithm SHA256).Hash.ToLowerInvariant()
 $signature=$rsa.SignData([Text.Encoding]::UTF8.GetBytes("Protocol Windows`n0.10.2`n$hash"),'SHA256')
 $manifest=@{version='0.10.2';sha256=$hash;signature=[Convert]::ToBase64String($signature)} | ConvertTo-Json
 [IO.File]::WriteAllText("$Dist/release.json",$manifest,[Text.UTF8Encoding]::new($false))
 $env:PROTOCOL_DIST=(Resolve-Path $Dist).Path
 & ./audio-runtime/python.exe -c "import os,zipfile,pathlib; p=pathlib.Path(os.environ['PROTOCOL_DIST']); z=zipfile.ZipFile(p/'Protocol-0.10.2.zip','w',zipfile.ZIP_STORED); [z.write(p/n,n) for n in ['ProtocolSetup.msi','release.json']];z.close()"
 if($LASTEXITCODE){throw 'Release build failed'}
}finally{Pop-Location;$rsa.Dispose()}


