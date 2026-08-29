' Launches the Telegram bot supervisor with no visible console window.
' Placed in the Windows Startup folder so it runs automatically at logon.
Set shell = CreateObject("WScript.Shell")
shell.Run "powershell.exe -WindowStyle Hidden -ExecutionPolicy Bypass -NoProfile -File ""C:\Users\rania\talent-live-ai-WhatsApp-agent\scripts\run_telegram_polling_forever.ps1""", 0, False
