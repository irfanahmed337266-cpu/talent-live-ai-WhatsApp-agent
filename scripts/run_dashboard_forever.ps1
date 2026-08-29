# Self-healing supervisor for the owner dashboard web server.
#
# Restarts uvicorn if it ever exits/crashes. Launched hidden at Windows
# logon via the Startup-folder entry (see scripts/launch_dashboard_hidden.vbs),
# so the dashboard runs in the background with no terminal window open -
# no external hosting account needed for an internal-only tool.

$root = "C:\Users\rania\talent-live-ai-WhatsApp-agent"
$python = "C:\Python314\python.exe"
$log = Join-Path $root "dashboard.log"

Set-Location $root

while ($true) {
    "$(Get-Date -Format o) [supervisor] starting dashboard" | Add-Content -Path $log -Encoding utf8

    $proc = Start-Process -FilePath $python `
        -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000" `
        -WorkingDirectory $root `
        -RedirectStandardOutput "$log.stdout.tmp" `
        -RedirectStandardError "$log.stderr.tmp" `
        -NoNewWindow -PassThru

    $proc.WaitForExit()

    Get-Content "$log.stdout.tmp" -ErrorAction SilentlyContinue | Add-Content -Path $log -Encoding utf8
    Get-Content "$log.stderr.tmp" -ErrorAction SilentlyContinue | Add-Content -Path $log -Encoding utf8
    Remove-Item "$log.stdout.tmp", "$log.stderr.tmp" -ErrorAction SilentlyContinue

    "$(Get-Date -Format o) [supervisor] dashboard exited, restarting in 5s" | Add-Content -Path $log -Encoding utf8
    Start-Sleep -Seconds 5
}
