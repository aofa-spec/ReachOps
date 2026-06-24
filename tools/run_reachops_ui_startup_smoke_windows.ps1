param(
    [string]$Root = "",
    [switch]$KeepRunning
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

$launcher = Join-Path $Root "tools\start_reachops_ui_windows.ps1"
$statePath = Join-Path $Root "reports\growth_ops_smoke\growth_ui_startup_state.json"
if (!(Test-Path $launcher)) {
    throw "ReachOps UI launcher missing: $launcher"
}

$output = & powershell -NoProfile -ExecutionPolicy Bypass -File $launcher -Root $Root -StopExisting -InteractiveTask -TaskName ReachOpsUISmoke 2>&1
$outputText = ($output -join [Environment]::NewLine)
Start-Sleep -Seconds 3

$state = $null
if (Test-Path $statePath) {
    $state = Get-Content $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
}

$pidValue = if ($state) { [int]$state.pid } else { 0 }
$process = $null
if ($pidValue -gt 0) {
    $process = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
}

$result = [ordered]@{
    status = "ok"
    launcher = $launcher
    state_path = $statePath
    pid = $pidValue
    process_running = ($null -ne $process)
    interactive_task = if ($state) { [bool]$state.interactive_task } else { $false }
    task_name = if ($state) { [string]$state.task_name } else { "" }
    stdout = $outputText
}

$failures = @()
if (!$state) { $failures += "startup_state_missing" }
if ($pidValue -le 0) { $failures += "pid_missing" }
if ($null -eq $process) { $failures += "process_not_running" }
if ($state -and -not [bool]$state.interactive_task) { $failures += "interactive_task_not_used" }

if ($failures.Count -gt 0) {
    $result.status = "failed"
    $result.failures = $failures
}

$json = $result | ConvertTo-Json -Compress
Write-Output $json

if (!$KeepRunning -and $process) {
    Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
}

if ($result.status -ne "ok") {
    exit 1
}
