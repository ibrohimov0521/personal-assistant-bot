$pattern = "assistant_bot.py"
$processes = @(Get-CimInstance Win32_Process | Where-Object {
    $command = $_.CommandLine
    $path = $_.ExecutablePath
    $path -and
    $path.ToLowerInvariant().EndsWith("python.exe") -and
    $command -and
    $command -like "*$pattern*" -and
    $_.ProcessId -ne $PID
})

foreach ($process in $processes) {
    Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
}

Write-Host "Stopped assistant_bot.py processes:" $processes.Count
