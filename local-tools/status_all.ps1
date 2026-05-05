$ToolsDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$patterns = @("assistant_bot.py", "forwarder.py", "cloudflared.exe")

foreach ($pattern in $patterns) {
    $processes = Get-CimInstance Win32_Process | Where-Object {
        $command = $_.CommandLine
        $path = $_.ExecutablePath
        if (-not $command) { return $false }
        if ($pattern -eq "cloudflared.exe") {
            return $path -and $path.ToLower().EndsWith("cloudflared.exe")
        }
        return $path -and $path.ToLower().EndsWith("python.exe") -and $command -like "*$pattern*"
    }
    $name = switch ($pattern) {
        "assistant_bot.py" { "Bot" }
        "forwarder.py" { "Forwarder" }
        default { "Cloudflare tunnel" }
    }
    if ($processes) {
        Write-Host "${name}: RUNNING"
    } else {
        Write-Host "${name}: STOPPED"
    }
}

$urlPath = Join-Path $ToolsDir "miniapp_url.txt"
if (Test-Path -LiteralPath $urlPath) {
    $url = (Get-Content -LiteralPath $urlPath -Raw).Trim()
    if ($url) {
        Write-Host "Mini App URL: $url"
    }
}
