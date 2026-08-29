# Registers the Telegram bot as a hidden background Scheduled Task.
#
# Run once:  powershell -ExecutionPolicy Bypass -File scripts\setup_telegram_task.ps1
# Remove:    Unregister-ScheduledTask -TaskName "TalentLiveTelegramBot" -Confirm:$false

$taskName = "TalentLiveTelegramBot"
$supervisor = "C:\Users\rania\talent-live-ai-WhatsApp-agent\scripts\run_telegram_polling_forever.ps1"

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-WindowStyle Hidden -ExecutionPolicy Bypass -NoProfile -File `"$supervisor`""

$trigger = New-ScheduledTaskTrigger -AtLogOn

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -RunLevel Limited `
    -Force

Write-Host "Registered scheduled task '$taskName'. It will start automatically at your next Windows logon."
Write-Host "Starting it now for this session too..."

Start-ScheduledTask -TaskName $taskName

Write-Host "Done. Logs: C:\Users\rania\talent-live-ai-WhatsApp-agent\telegram_polling.log"
