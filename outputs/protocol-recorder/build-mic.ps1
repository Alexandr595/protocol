param([switch]$TestFileSource)
$ErrorActionPreference='Stop'
$fx="$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319"
$refs=@('Windows.Foundation','Windows.Media','Windows.Devices','Windows.Storage','Windows.System') | ForEach-Object {"/reference:$env:WINDIR\System32\WinMetadata\$_.winmd"}
$extra=@();$out="WindowsMic.exe";if($TestFileSource){$out="MicGraphProof.exe";$extra=@("/define:TEST_INPUT")}
& "$fx\csc.exe" $extra /nologo /platform:x64 "/out:$PSScriptRoot\$out" $refs "/reference:$fx\System.Runtime.WindowsRuntime.dll" "/reference:$fx\System.Runtime.dll" "/reference:$fx\System.Runtime.InteropServices.WindowsRuntime.dll" /reference:System.Web.Extensions.dll "$PSScriptRoot\WindowsMic.cs"
if($LASTEXITCODE){throw 'Сборка микрофонного процесса не удалась.'}


