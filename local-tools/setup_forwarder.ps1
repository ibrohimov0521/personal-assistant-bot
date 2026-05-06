$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

function Prompt-Value {
    param(
        [string]$Label,
        [string]$Default = ""
    )
    if ($Default) {
        $value = Read-Host "$Label [$Default]"
        if ([string]::IsNullOrWhiteSpace($value)) {
            return $Default
        }
        return $value.Trim()
    }
    return (Read-Host $Label).Trim()
}

Write-Host ""
Write-Host "Assistant forwarder sozlash"
Write-Host "Bu sozlama faqat shu kompyuterda saqlanadi: forwarder.local.env"
Write-Host ""

$apiId = Prompt-Value "TG_API_ID (my.telegram.org)"
$apiHash = Prompt-Value "TG_API_HASH (my.telegram.org)"
$assistantBot = Prompt-Value "Assistant bot username" "@bestgamers_assistantbot"
$sourceBots = Prompt-Value "Bank bot username'lari vergul bilan" "@CardXabarBot,@HUMOcardbot"

$envText = @"
TG_API_ID=$apiId
TG_API_HASH=$apiHash
ASSISTANT_BOT_USERNAME=$assistantBot
SOURCE_BOT_USERNAMES=$sourceBots
"@

Set-Content -Path (Join-Path $ProjectRoot "forwarder.local.env") -Value $envText -Encoding UTF8
Write-Host ""
Write-Host "forwarder.local.env saqlandi."

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    Write-Host "Virtual env yaratilmoqda..."
    python -m venv .venv
}

Write-Host "Kerakli paketlar tekshirilmoqda..."
& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt

$env:FORWARDER_ENV_FILE = Join-Path $ProjectRoot "forwarder.local.env"
Write-Host ""
Write-Host "Forwarder ishga tushyapti. Telegram kodi shu oynada so'raladi."
& ".\.venv\Scripts\python.exe" forwarder.py
