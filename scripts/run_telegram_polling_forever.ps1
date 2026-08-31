# Self-healing supervisor for the Telegram long-polling bot.
#
# Restarts app/telegram_polling.py if it ever exits/crashes. Launched hidden
# at Windows logon via a Startup-folder entry created by
# scripts/install_bot_autostart.ps1 (run that once per machine).
#
# Portable: finds its own location and the python interpreter on PATH, so
# this same repo checkout works unmodified on any Windows machine - no
# machine-specific paths hardcoded here.

$root = Split-Path $PSScriptRoot -Parent
$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) { $python = (Get-Command py -ErrorAction SilentlyContinue).Source }
if (-not $python) {
    "$(Get-Date -Format o) [supervisor] FATAL: no python/py found on PATH" | Add-Content -Path (Join-Path $root "telegram_polling.log")
    exit 1
}
$log = Join-Path $root "telegram_polling.log"

Set-Location $root

while ($true) {
    "$(Get-Date -Format o) [supervisor] starting telegram_polling" | Add-Content -Path $log -Encoding utf8

    $proc = Start-Process -FilePath $python `
        -ArgumentList "-u", "-m", "app.telegram_polling" `
        -WorkingDirectory $root `
        -RedirectStandardOutput "$log.stdout.tmp" `
        -RedirectStandardError "$log.stderr.tmp" `
        -NoNewWindow -PassThru

    $proc.WaitForExit()

    Get-Content "$log.stdout.tmp" -ErrorAction SilentlyContinue | Add-Content -Path $log -Encoding utf8
    Get-Content "$log.stderr.tmp" -ErrorAction SilentlyContinue | Add-Content -Path $log -Encoding utf8
    Remove-Item "$log.stdout.tmp", "$log.stderr.tmp" -ErrorAction SilentlyContinue

    "$(Get-Date -Format o) [supervisor] polling process exited, restarting in 5s" | Add-Content -Path $log -Encoding utf8
    Start-Sleep -Seconds 5
}
