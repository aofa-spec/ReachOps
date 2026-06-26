param(
    [string]$RunDir = "",
    [switch]$Json
)

$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 | Out-Null

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

function Read-JsonObject {
    param([string]$Path)
    if (!(Test-Path $Path)) {
        return $null
    }
    return Get-Content -Path $Path -Raw -Encoding UTF8 | ConvertFrom-Json -ErrorAction Stop
}

function Convert-StdoutJson {
    param([string]$Raw)
    if ([string]::IsNullOrWhiteSpace($Raw)) {
        return $null
    }
    $idx = $Raw.LastIndexOf("{")
    while ($idx -ge 0) {
        $candidate = $Raw.Substring($idx).Trim()
        try {
            return $candidate | ConvertFrom-Json -ErrorAction Stop
        } catch {
            if ($idx -eq 0) {
                break
            }
            $idx = $Raw.LastIndexOf("{", $idx - 1)
        }
    }
    return $null
}

if (-not $RunDir) {
    $latest = Get-ChildItem "reports\reachops_acceptance_background" -Directory -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending |
        Select-Object -First 1
    if ($latest) {
        $RunDir = $latest.FullName
    }
}

if (-not $RunDir) {
    $result = [ordered]@{
        status = "missing"
        error = "no background acceptance run found"
    }
    if ($Json) {
        Write-Host ($result | ConvertTo-Json -Depth 8 -Compress)
    } else {
        Write-Host "ReachOps background acceptance status: missing"
    }
    exit 2
}

$recordPath = Join-Path $RunDir "acceptance_background_run.json"
$record = Read-JsonObject $recordPath
$processId = if ($record) { [int]$record.pid } else { 0 }
$taskName = if ($record -and $record.task_name) { [string]$record.task_name } else { "" }
$taskState = ""
$taskLastResult = $null
$running = $false
if ($processId -gt 0) {
    $running = [bool](Get-Process -Id $processId -ErrorAction SilentlyContinue)
}
if ($taskName) {
    $taskInfo = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($taskInfo) {
        $taskState = [string]$taskInfo.State
        $taskDetails = Get-ScheduledTaskInfo -TaskName $taskName -ErrorAction SilentlyContinue
        if ($taskDetails) {
            $taskLastResult = $taskDetails.LastTaskResult
        }
        if ($taskState -eq "Running") {
            $running = $true
        }
    }
}

$stdoutPath = if ($record -and $record.stdout_path) { [string]$record.stdout_path } else { Join-Path $RunDir "acceptance_stdout.log" }
$stderrPath = if ($record -and $record.stderr_path) { [string]$record.stderr_path } else { Join-Path $RunDir "acceptance_stderr.log" }
$stdoutTail = ""
$stderrTail = ""
if (Test-Path $stdoutPath) {
    $stdoutTail = ((Get-Content -Path $stdoutPath -Tail 40 -Encoding UTF8) -join [Environment]::NewLine)
}
if (Test-Path $stderrPath) {
    $stderrTail = ((Get-Content -Path $stderrPath -Tail 40 -Encoding UTF8) -join [Environment]::NewLine)
}

$acceptanceSummaryPath = ""
if (Test-Path $stdoutPath) {
    $summaryLine = Get-Content -Path $stdoutPath -Encoding UTF8 |
        Where-Object { $_ -like "ACCEPTANCE_SUMMARY_JSON=*" } |
        Select-Object -Last 1
    if ($summaryLine) {
        $acceptanceSummaryPath = [string]$summaryLine.Substring("ACCEPTANCE_SUMMARY_JSON=".Length)
    }
}

$acceptanceSummary = $null
$acceptanceVerification = $null
if ($acceptanceSummaryPath -and (Test-Path $acceptanceSummaryPath)) {
    $acceptanceSummary = Read-JsonObject $acceptanceSummaryPath
    $verifyOutput = & python tools\verify_reachops_acceptance_summary.py $acceptanceSummaryPath --allow-external-pending --json 2>&1
    $acceptanceVerification = Convert-StdoutJson (($verifyOutput | ForEach-Object { [string]$_ }) -join [Environment]::NewLine)
}

$status = "running"
if (-not $running) {
    if ($acceptanceSummary) {
        $status = [string]$acceptanceSummary.status
    } elseif ($null -ne $taskLastResult -and [int]$taskLastResult -ne 0) {
        $status = "failed"
    } elseif ($stderrTail) {
        $status = "failed"
    } else {
        $status = "exited_without_summary"
    }
}

$result = [ordered]@{
    status = $status
    running = $running
    pid = $processId
    task_name = $taskName
    task_state = $taskState
    task_last_result = $taskLastResult
    run_dir = $RunDir
    record_path = $recordPath
    stdout_path = $stdoutPath
    stderr_path = $stderrPath
    acceptance_summary_path = $acceptanceSummaryPath
    acceptance_summary_exists = [bool]($acceptanceSummaryPath -and (Test-Path $acceptanceSummaryPath))
    acceptance_verification = $acceptanceVerification
    stdout_tail = $stdoutTail
    stderr_tail = $stderrTail
}

if ($Json) {
    Write-Host ($result | ConvertTo-Json -Depth 12 -Compress)
} else {
    Write-Host "ReachOps background acceptance status: $status"
    Write-Host "RUN_DIR=$RunDir"
    Write-Host "PID=$processId"
    if ($taskName) {
        Write-Host "TASK_NAME=$taskName"
        Write-Host "TASK_STATE=$taskState"
        Write-Host "TASK_LAST_RESULT=$taskLastResult"
    }
    Write-Host "RUNNING=$running"
    if ($acceptanceSummaryPath) {
        Write-Host "ACCEPTANCE_SUMMARY_JSON=$acceptanceSummaryPath"
    }
}
