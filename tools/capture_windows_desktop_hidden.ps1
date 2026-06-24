$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root
Start-Process -FilePath "C:\Python311-x64\pythonw.exe" -ArgumentList "tools\capture_windows_desktop.py --output reports\growth_ops_smoke\windows_ui_screenshot.png --delay 2" -WorkingDirectory $Root -WindowStyle Hidden
