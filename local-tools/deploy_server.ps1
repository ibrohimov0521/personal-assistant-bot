param(
    [string]$HostName = "138.2.3.96",
    [string]$User = "ubuntu",
    [string]$KeyPath = "$env:USERPROFILE\Downloads\ssh-key-2026-05-03.key",
    [string]$RemoteDir = "/opt/assistant-bot"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Remote = "$User@$HostName"

Push-Location $Root
try {
    $pythonFiles = @(
        "assistant_bot.py",
        "access_control.py",
        "ai_assistant.py",
        "db.py",
        "db_schema.py",
        "finance.py",
        "finance_store.py",
        "fsm_sqlite_storage.py",
        "miniapp_api.py",
        "miniapp_auth.py",
        "prayer_store.py",
        "prayer_times.py",
        "reminder_store.py",
        "reminders.py",
        "user_store.py",
        "forwarder.py",
        "README.md"
    )
    $miniappFiles = @(
        "miniapp\index.html",
        "miniapp\app.js",
        "miniapp\demo-data.js",
        "miniapp\styles.css",
        "miniapp\theme.css"
    )

    scp -i $KeyPath @pythonFiles "$Remote`:$RemoteDir/"
    scp -i $KeyPath @miniappFiles "$Remote`:$RemoteDir/miniapp/"
    scp -i $KeyPath -r handlers tests "$Remote`:$RemoteDir/"

    $remoteCommand = @"
cd $RemoteDir &&
.venv/bin/python -m py_compile assistant_bot.py ai_assistant.py handlers/admin.py db_schema.py reminder_store.py prayer_store.py miniapp_api.py miniapp_auth.py finance_store.py user_store.py &&
.venv/bin/python -m unittest discover -s tests &&
sudo systemctl restart assistant-bot &&
sleep 5 &&
systemctl is-active assistant-bot assistant-forwarder cloudflared &&
curl -I -s https://app.bestgamers.win/ | head -n 8
"@

    ssh -i $KeyPath $Remote $remoteCommand
}
finally {
    Pop-Location
}
