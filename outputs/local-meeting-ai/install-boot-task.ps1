$ErrorActionPreference = 'Stop'
try {
    $project = (Get-Item -LiteralPath $PSScriptRoot).FullName
    $profiles = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList\*'
    $owner = $profiles | Where-Object {
        $folder = [Environment]::ExpandEnvironmentVariables($_.ProfileImagePath).TrimEnd('\')
        $project.StartsWith($folder + '\', [StringComparison]::OrdinalIgnoreCase)
    } | Select-Object -First 1
    if (-not $owner) { throw 'Не удалось определить владельца профиля, в котором установлен сервер.' }
    $profileDir = [Environment]::ExpandEnvironmentVariables($owner.ProfileImagePath)
    $python = Join-Path $profileDir '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    $entry = Join-Path $project 'boot_server.py'
    if (!(Test-Path -LiteralPath $python) -or !(Test-Path -LiteralPath $entry)) { throw 'Не найден Python или файл запуска сервера.' }
    $account = ([Security.Principal.SecurityIdentifier]$owner.PSChildName).Translate([Security.Principal.NTAccount]).Value
    $step = 'подключение к Планировщику Windows'
    $scheduler = New-Object -ComObject Schedule.Service
    $scheduler.Connect()
    $folder = $scheduler.GetFolder('\')
    $task = $scheduler.NewTask(0)
    $task.RegistrationInfo.Description = 'Протокол: сервер встреч'
    $task.Principal.UserId = $account
    $task.Principal.LogonType = 2 # S4U
    $task.Principal.RunLevel = 0
    $task.Settings.ExecutionTimeLimit = 'PT0S'
    $task.Settings.DisallowStartIfOnBatteries = $false
    $task.Settings.StopIfGoingOnBatteries = $false
    $task.Settings.StartWhenAvailable = $true
    $task.Settings.RestartInterval = 'PT1M'
    $task.Settings.RestartCount = 5
    $null = $task.Triggers.Create(8) # boot
    $exec = $task.Actions.Create(0)
    $exec.Path = $python
    $exec.Arguments = '"' + $entry + '"'
    $exec.WorkingDirectory = $project
    $name = 'Protocol - Meeting Server'
    $step = "регистрация задания для $account"
    try {
        $registered = $folder.RegisterTaskDefinition($name,$task,6,$account,$null,2,$null)
    } catch {
        $cause = $_.Exception.GetBaseException()
        if ($cause.HResult -notin -2147024891,-2147023573,-2147023585) { throw }
        Write-Host "Windows отклонила запуск без пароля для $account. Для регистрации можно ввести пароль этой учётной записи Windows."
        $cred = Get-Credential -UserName $account -Message 'Пароль Windows для запуска Протокола до входа пользователя'
        if (!$cred) { throw 'Регистрация отменена.' }
        $task.Principal.LogonType = 1
        $registered = $folder.RegisterTaskDefinition($name,$task,6,$account,$cred.GetNetworkCredential().Password,1,$null)
    }
    $step = 'проверка зарегистрированного задания'
    if (!$registered.Enabled -or $registered.Definition.Triggers.Item(1).Type -ne 8) { throw 'Задание при загрузке не подтверждено.' }
    Write-Host "Готово. При следующей загрузке Windows сервер запустится до входа пользователя ($account)." -ForegroundColor Green
} catch {
    Write-Host ("Ошибка ({0}, строка {1}): {2}" -f $step,$_.InvocationInfo.ScriptLineNumber,$_.Exception.GetBaseException().Message) -ForegroundColor Red
    exit 1
}
