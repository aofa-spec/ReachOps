param(
    [string]$Root = "",
    [string]$Pythonw = "C:\Python311-x64\pythonw.exe",
    [switch]$StopExisting,
    [switch]$InteractiveTask,
    [string]$TaskName = "ReachOpsUI"
)

$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

if ([string]::IsNullOrWhiteSpace($Root)) {
    $Root = Resolve-Path (Join-Path $PSScriptRoot "..")
} else {
    $Root = Resolve-Path $Root
}

$logDir = Join-Path $Root "reports\growth_ops_smoke"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$startupLog = Join-Path $logDir "growth_ui_startup.log"
$startupState = Join-Path $logDir "growth_ui_startup_state.json"

if (!(Test-Path $Pythonw)) {
    throw "pythonw.exe not found: $Pythonw"
}

$entrypoint = "ReachOpsApp.py"
if (!(Test-Path (Join-Path $Root $entrypoint))) {
    throw "$entrypoint not found under $Root"
}

if ($StopExisting) {
    Get-Process python,pythonw -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
}

if ($InteractiveTask) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    $action = New-ScheduledTaskAction -Execute $Pythonw -Argument $entrypoint -WorkingDirectory $Root
    $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5)
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -User $env:USERNAME -RunLevel Limited -Force | Out-Null
    Start-ScheduledTask -TaskName $TaskName
    Start-Sleep -Seconds 2
    $process = Get-Process pythonw -ErrorAction SilentlyContinue | Sort-Object StartTime -Descending | Select-Object -First 1
} else {
    $process = Start-Process -FilePath $Pythonw -ArgumentList $entrypoint -WorkingDirectory $Root -PassThru
}

if ($null -eq $process) {
    throw "ReachOps UI process did not start."
}

$payload = [ordered]@{
    status = "started"
    pid = $process.Id
    root = [string]$Root
    pythonw = $Pythonw
    entrypoint = $entrypoint
    launcher = "start_reachops_ui_windows.ps1"
    interactive_task = [bool]$InteractiveTask
    task_name = if ($InteractiveTask) { $TaskName } else { "" }
    started_at = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
}
$json = $payload | ConvertTo-Json -Compress
[System.IO.File]::WriteAllText($startupState, $json, [System.Text.UTF8Encoding]::new($false))
[System.IO.File]::WriteAllText($startupLog, $json + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))
Write-Output $json
