# Self-healing supervisor for the Telegram long-polling bot.
#
# Restarts app/telegram_polling.py if it ever exits/crashes. Launched hidden
# at Windows logon via the Startup-folder entry (see scripts/launch_telegram_bot_hidden.vbs),
# so the bot runs in the background with no terminal window open.

$root = "C:\Users\rania\talent-live-ai-WhatsApp-agent"
$python = "C:\Users\rania\AppData\Local\Programs\Python\Python313\python.exe"
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
