# Stops the local Telegram bot and removes its Startup-folder autostart
# entry on THIS machine. Run this on the OLD machine once the bot is
# confirmed working on its new machine - never run it on both at once
# while migrating, or there'll be a gap with no poller running at all.
#
#   powershell -ExecutionPolicy Bypass -File scripts\uninstall_bot_autostart.ps1

$myPid = $PID

1..3 | ForEach-Object {
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -match "app\.telegram_polling" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

    Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
        Where-Object { $_.ProcessId -ne $myPid -and $_.CommandLine -match "run_telegram_polling_forever" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

    Start-Sleep -Seconds 2
}

$startupFolder = [Environment]::GetFolderPath("Startup")
$vbsPath = Join-Path $startupFolder "TalentLiveTelegramBot.vbs"
Remove-Item $vbsPath -Force -ErrorAction SilentlyContinue

Write-Host "Stopped the bot and removed the Startup entry on this machine."
Write-Host "It will no longer start automatically here, and is not currently running."
