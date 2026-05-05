$patterns = @("assistant_bot.py", "forwarder.py", "cloudflared.exe")
$processes = Get-CimInstance Win32_Process | Where-Object {
    $command = $_.CommandLine
    $path = $_.ExecutablePath
    if (-not $command) { return $false }
    if ($path -and $path.ToLower().EndsWith("cloudflared.exe")) { return $true }
    if (-not ($path -and $path.ToLower().EndsWith("python.exe"))) { return $false }
    foreach ($pattern in $patterns) {
        if ($pattern -ne "cloudflared.exe" -and $command -like "*$pattern*") { return $true }
    }
    return $false
}

foreach ($process in $processes) {
    if ($process.ProcessId -ne $PID) {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

Write-Host "Stopped processes:" $processes.Count
