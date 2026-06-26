param(
    [string]$ProfileGroup = "BR",
    [string]$ProfileIds = "",
    [string]$Target = "anti aging serum",
    [string]$CommentVideoUrl = "",
    [string]$FollowProfileUrl = "",
    [string]$DmProfileUrl = "",
    [string]$TargetUsername = "",
    [string]$ActivationStatusPath = "",
    [int]$Limit = 3,
    [string]$AllowPressureSubmit = "",
    [switch]$AllowMissingInstaller,
    [switch]$RunLiveSubmit,
    [switch]$ConfirmAuthorizedTargets
)

$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 | Out-Null

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

function Write-Utf8NoBom {
    param(
        [string]$Path,
        [string]$Content
    )
    $fullPath = [System.IO.Path]::GetFullPath((Join-Path (Get-Location).ProviderPath $Path))
    $dir = [System.IO.Path]::GetDirectoryName($fullPath)
    if ($dir -and -not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    [System.IO.File]::WriteAllText($fullPath, $Content, [System.Text.UTF8Encoding]::new($false))
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$runRoot = "reports\reachops_acceptance_background\$stamp"
New-Item -ItemType Directory -Path $runRoot -Force | Out-Null
$stdoutPath = Join-Path $runRoot "acceptance_stdout.log"
$stderrPath = Join-Path $runRoot "acceptance_stderr.log"
$recordPath = Join-Path $runRoot "acceptance_background_run.json"

$argsList = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", "tools\run_reachops_acceptance_windows.ps1",
    "-ProfileGroup", $ProfileGroup,
    "-Target", $Target,
    "-Limit", ([string]$Limit)
)
if ($ProfileIds) { $argsList += @("-ProfileIds", $ProfileIds) }
if ($CommentVideoUrl) { $argsList += @("-CommentVideoUrl", $CommentVideoUrl) }
if ($FollowProfileUrl) { $argsList += @("-FollowProfileUrl", $FollowProfileUrl) }
if ($DmProfileUrl) { $argsList += @("-DmProfileUrl", $DmProfileUrl) }
if ($TargetUsername) { $argsList += @("-TargetUsername", $TargetUsername) }
if ($ActivationStatusPath) { $argsList += @("-ActivationStatusPath", $ActivationStatusPath) }
if ($AllowPressureSubmit) { $argsList += @("-AllowPressureSubmit", $AllowPressureSubmit) }
if ($AllowMissingInstaller) { $argsList += @("-AllowMissingInstaller") }
if ($RunLiveSubmit) { $argsList += @("-RunLiveSubmit") }
if ($ConfirmAuthorizedTargets) { $argsList += @("-ConfirmAuthorizedTargets") }

$process = Start-Process `
    -FilePath "powershell" `
    -ArgumentList $argsList `
    -WorkingDirectory (Get-Location).ProviderPath `
    -RedirectStandardOutput $stdoutPath `
    -RedirectStandardError $stderrPath `
    -PassThru

$record = [ordered]@{
    status = "running"
    started_at = (Get-Date).ToUniversalTime().ToString("o")
    pid = [int]$process.Id
    run_dir = $runRoot
    stdout_path = $stdoutPath
    stderr_path = $stderrPath
    no_submit = (-not [bool]$RunLiveSubmit)
    run_live_submit = [bool]$RunLiveSubmit
    confirm_authorized_targets = [bool]$ConfirmAuthorizedTargets
    command = "powershell " + (($argsList | ForEach-Object { if ($_ -match "\s") { '"' + $_ + '"' } else { $_ } }) -join " ")
}
Write-Utf8NoBom -Path $recordPath -Content ($record | ConvertTo-Json -Depth 6 -Compress)

Write-Host "REACHOPS_ACCEPTANCE_BACKGROUND_RUN=$runRoot"
Write-Host "ACCEPTANCE_BACKGROUND_RECORD=$recordPath"
Write-Host "ACCEPTANCE_BACKGROUND_PID=$($process.Id)"
