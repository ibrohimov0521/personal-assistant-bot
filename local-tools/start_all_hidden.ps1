$ToolsDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Project = Split-Path -Parent $ToolsDir
$Python = Join-Path $Project ".venv\Scripts\python.exe"
$Cloudflared = Join-Path $env:USERPROFILE "Downloads\cloudflared.exe"
$BotLog = Join-Path $Project "assistant_runtime.log"
$ForwarderLog = Join-Path $Project "forwarder_runtime.log"
$CloudflaredLog = Join-Path $Project "cloudflared_runtime.log"
$MiniappUrlFile = Join-Path $ToolsDir "miniapp_url.txt"

function Get-MatchingProcesses {
    param([string[]]$Patterns)

    $includeCloudflared = $Patterns -contains "cloudflared.exe"
    Get-CimInstance Win32_Process | Where-Object {
        $command = $_.CommandLine
        $path = $_.ExecutablePath
        if (-not $path) { return $false }

        $lowerPath = $path.ToLowerInvariant()
        if ($includeCloudflared -and $lowerPath.EndsWith("cloudflared.exe")) { return $true }
        if (-not ($lowerPath.EndsWith("python.exe"))) { return $false }
        if (-not $command) { return $false }

        foreach ($pattern in $Patterns) {
            if ($pattern -ne "cloudflared.exe" -and $command -like "*$pattern*") { return $true }
        }
        return $false
    }
}

function Stop-MatchingProcess {
    param([string[]]$Patterns)

    $processes = @(Get-MatchingProcesses $Patterns)
    foreach ($process in $processes) {
        if ($process.ProcessId -ne $PID) {
            Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
        }
    }
}

function Set-MiniAppUrl {
    param([string]$Url)

    $envPath = Join-Path $Project ".env"
    if (-not (Test-Path -LiteralPath $envPath)) {
        throw ".env topilmadi: $envPath"
    }

    $content = [System.IO.File]::ReadAllText($envPath, [System.Text.Encoding]::UTF8).TrimStart([char]0xFEFF)
    if ($content -match "(?m)^MINI_APP_URL=") {
        $content = $content -replace "(?m)^MINI_APP_URL=.*", "MINI_APP_URL=$Url"
    } else {
        if (-not $content.EndsWith("`n")) { $content += "`n" }
        $content += "MINI_APP_URL=$Url`n"
    }

    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($envPath, $content, $utf8NoBom)
    Set-Content -LiteralPath $MiniappUrlFile -Value $Url -Encoding UTF8
}

function Get-CurrentMiniAppUrl {
    if (-not (Test-Path -LiteralPath $MiniappUrlFile)) {
        return $null
    }
    $url = (Get-Content -LiteralPath $MiniappUrlFile -Raw -ErrorAction SilentlyContinue).Trim()
    if ($url -match "^https://[a-z0-9-]+\.trycloudflare\.com/?$") {
        return $url.TrimEnd("/")
    }
    return $null
}

function Test-CloudflareUrl {
    param([string]$Url)

    if (-not $Url) { return $false }
    try {
        $hostName = ([Uri]$Url).Host
        Resolve-DnsName $hostName -ErrorAction Stop | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Start-HiddenCommand {
    param(
        [string]$Command,
        [string]$LogPath
    )

    $fullCommand = "cd /d `"$Project`" && $Command >> `"$LogPath`" 2>&1"
    Start-Process -FilePath "cmd.exe" -ArgumentList "/c $fullCommand" -WindowStyle Hidden
}

function Start-CloudflareTunnel {
    if (-not (Test-Path -LiteralPath $Cloudflared)) {
        "cloudflared.exe topilmadi: $Cloudflared" | Set-Content -LiteralPath $CloudflaredLog -Encoding UTF8
        return $null
    }

    Remove-Item -LiteralPath $CloudflaredLog -Force -ErrorAction SilentlyContinue
    $cloudCommand = "`"$Cloudflared`" tunnel --protocol http2 --url http://127.0.0.1:8080"
    Start-HiddenCommand -Command $cloudCommand -LogPath $CloudflaredLog

    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 1
        if (Test-Path -LiteralPath $CloudflaredLog) {
            $text = Get-Content -LiteralPath $CloudflaredLog -Raw -ErrorAction SilentlyContinue
            $match = [regex]::Match($text, "https://[a-z0-9-]+\.trycloudflare\.com")
            if ($match.Success) {
                return $match.Value
            }
        }
    }

    "Cloudflare URL topilmadi. $CloudflaredLog faylini tekshiring." | Add-Content -LiteralPath $CloudflaredLog
    return $null
}

if (-not (Test-Path -LiteralPath $Python)) {
    py -m venv "$Project\.venv"
}

Stop-MatchingProcess @("assistant_bot.py", "forwarder.py")
Start-Sleep -Seconds 2

Remove-Item -LiteralPath $BotLog, $ForwarderLog -Force -ErrorAction SilentlyContinue

$currentUrl = Get-CurrentMiniAppUrl
$cloudflaredRunning = @(Get-MatchingProcesses @("cloudflared.exe")).Count -gt 0
$currentUrlHealthy = Test-CloudflareUrl $currentUrl

if ($cloudflaredRunning -and $currentUrl -and $currentUrlHealthy) {
    Set-MiniAppUrl -Url $currentUrl
    Write-Host "Reusing Cloudflare URL: $currentUrl"
} else {
    if ($cloudflaredRunning -and $currentUrl -and -not $currentUrlHealthy) {
        Write-Host "Cloudflare URL is not resolving anymore. Restarting tunnel..."
    }
    Stop-MatchingProcess @("cloudflared.exe")
    Start-Sleep -Seconds 1
    $newUrl = Start-CloudflareTunnel
    if ($newUrl) {
        Set-MiniAppUrl -Url $newUrl
    }
}

Start-HiddenCommand -Command "`"$Python`" assistant_bot.py" -LogPath $BotLog
Start-HiddenCommand -Command "`"$Python`" forwarder.py" -LogPath $ForwarderLog

Start-Sleep -Seconds 4
& (Join-Path $ToolsDir "status_all.ps1")
