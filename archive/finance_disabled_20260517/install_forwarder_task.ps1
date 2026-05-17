$ToolsDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Project = Split-Path -Parent $ToolsDir
$Python = Join-Path $Project ".venv\Scripts\python.exe"
$Forwarder = Join-Path $Project "forwarder.py"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python venv topilmadi: $Python"
}
if (-not (Test-Path -LiteralPath $Forwarder)) {
    throw "forwarder.py topilmadi: $Forwarder"
}

$action = New-ScheduledTaskAction -Execute $Python -Argument "`"$Forwarder`"" -WorkingDirectory $Project
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName "AssistantForwarder" -Action $action -Trigger $trigger -Settings $settings -Description "Forward UZCARD/HUMO bot messages to assistant bot" -Force | Out-Null
Start-ScheduledTask -TaskName "AssistantForwarder"
Get-ScheduledTask -TaskName "AssistantForwarder" | Select-Object TaskName,State
