param(
    [string]$InputFile = "",
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
    if ([System.IO.Path]::IsPathRooted($Path)) {
        $fullPath = [System.IO.Path]::GetFullPath($Path)
    } else {
        $fullPath = [System.IO.Path]::GetFullPath((Join-Path (Get-Location).ProviderPath $Path))
    }
    $dir = [System.IO.Path]::GetDirectoryName($fullPath)
    if ($dir -and -not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    [System.IO.File]::WriteAllText($fullPath, $Content, [System.Text.UTF8Encoding]::new($false))
}

function Quote-ProcessArgument {
    param([string]$Value)
    $text = [string]$Value
    if ($text -notmatch '[\s"]') {
        return $text
    }
    return '"' + ($text -replace '"', '\"') + '"'
}

function Quote-PowerShellLiteral {
    param([string]$Value)
    $escaped = ([string]$Value).Replace("'", "''")
    return "'$escaped'"
}

function Convert-AcceptanceInputLiteral {
    param([string]$Value)
    $text = ([string]$Value).Trim()
    if ($text -match '^\$true$') {
        return $true
    }
    if ($text -match '^\$false$') {
        return $false
    }
    if ($text -match '^-?\d+$') {
        return [int]$text
    }
    if ($text -match '^"(.*)"$') {
        return (($Matches[1] -replace '""', '"') -replace '`"', '"')
    }
    if ($text -match "^'(.*)'$") {
        return ($Matches[1] -replace "''", "'")
    }
    return $text
}

function Import-AcceptanceInputFile {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) {
        return
    }
    $inputPath = if ([System.IO.Path]::IsPathRooted($Path)) {
        [System.IO.Path]::GetFullPath($Path)
    } else {
        [System.IO.Path]::GetFullPath((Join-Path (Get-Location).ProviderPath $Path))
    }
    if (-not (Test-Path $inputPath)) {
        throw "InputFile does not exist: $inputPath"
    }
    foreach ($line in Get-Content -Path $inputPath -Encoding UTF8) {
        if ($line -match '^\s*\$(ProfileGroup|ProfileIds|Target|CommentVideoUrl|FollowProfileUrl|DmProfileUrl|TargetUsername|ActivationStatusPath|Limit|AllowPressureSubmit|ConfirmAuthorizedTargets|RunControlledLiveSubmit)\s*=\s*(.+?)\s*$') {
            $name = $Matches[1]
            $value = Convert-AcceptanceInputLiteral $Matches[2]
            switch ($name) {
                "ProfileGroup" { $script:ProfileGroup = [string]$value }
                "ProfileIds" { $script:ProfileIds = [string]$value }
                "Target" { $script:Target = [string]$value }
                "CommentVideoUrl" { $script:CommentVideoUrl = [string]$value }
                "FollowProfileUrl" { $script:FollowProfileUrl = [string]$value }
                "DmProfileUrl" { $script:DmProfileUrl = [string]$value }
                "TargetUsername" { $script:TargetUsername = [string]$value }
                "ActivationStatusPath" { $script:ActivationStatusPath = [string]$value }
                "Limit" { $script:Limit = [int]$value }
                "AllowPressureSubmit" { $script:AllowPressureSubmit = [string]$value }
                "ConfirmAuthorizedTargets" { $script:ConfirmAuthorizedTargets = [bool]$value }
                "RunControlledLiveSubmit" { $script:RunLiveSubmit = [bool]$value }
            }
        }
    }
}

Import-AcceptanceInputFile $InputFile

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$runRoot = "reports\reachops_acceptance_background\$stamp"
New-Item -ItemType Directory -Path $runRoot -Force | Out-Null
$stdoutPath = [System.IO.Path]::GetFullPath((Join-Path (Get-Location).ProviderPath (Join-Path $runRoot "acceptance_stdout.log")))
$stderrPath = [System.IO.Path]::GetFullPath((Join-Path (Get-Location).ProviderPath (Join-Path $runRoot "acceptance_stderr.log")))
$recordPath = [System.IO.Path]::GetFullPath((Join-Path (Get-Location).ProviderPath (Join-Path $runRoot "acceptance_background_run.json")))
$commandScriptPath = [System.IO.Path]::GetFullPath((Join-Path (Get-Location).ProviderPath (Join-Path $runRoot "acceptance_command.ps1")))
$taskName = "ReachOpsAcceptance_$stamp"

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
if ($InputFile) { $argsList += @("-InputFile", $InputFile) }
$argsList += @("-ReuseExistingUiStartup")
if ($RunLiveSubmit) { $argsList += @("-RunLiveSubmit") }
if ($ConfirmAuthorizedTargets) { $argsList += @("-ConfirmAuthorizedTargets") }
$argumentLine = ($argsList | ForEach-Object { Quote-ProcessArgument $_ }) -join " "

$commandLine = '& powershell.exe -NoProfile -ExecutionPolicy Bypass -File ' +
    (Quote-PowerShellLiteral "tools\run_reachops_acceptance_windows.ps1") +
    ' -ProfileGroup ' + (Quote-PowerShellLiteral $ProfileGroup) +
    ' -Target ' + (Quote-PowerShellLiteral $Target) +
    ' -Limit ' + (Quote-PowerShellLiteral ([string]$Limit))
if ($ProfileIds) { $commandLine += ' -ProfileIds ' + (Quote-PowerShellLiteral $ProfileIds) }
if ($CommentVideoUrl) { $commandLine += ' -CommentVideoUrl ' + (Quote-PowerShellLiteral $CommentVideoUrl) }
if ($FollowProfileUrl) { $commandLine += ' -FollowProfileUrl ' + (Quote-PowerShellLiteral $FollowProfileUrl) }
if ($DmProfileUrl) { $commandLine += ' -DmProfileUrl ' + (Quote-PowerShellLiteral $DmProfileUrl) }
if ($TargetUsername) { $commandLine += ' -TargetUsername ' + (Quote-PowerShellLiteral $TargetUsername) }
if ($ActivationStatusPath) { $commandLine += ' -ActivationStatusPath ' + (Quote-PowerShellLiteral $ActivationStatusPath) }
if ($AllowPressureSubmit) { $commandLine += ' -AllowPressureSubmit ' + (Quote-PowerShellLiteral $AllowPressureSubmit) }
if ($AllowMissingInstaller) { $commandLine += ' -AllowMissingInstaller' }
if ($InputFile) { $commandLine += ' -InputFile ' + (Quote-PowerShellLiteral $InputFile) }
$commandLine += ' -ReuseExistingUiStartup'
if ($RunLiveSubmit) { $commandLine += ' -RunLiveSubmit' }
if ($ConfirmAuthorizedTargets) { $commandLine += ' -ConfirmAuthorizedTargets' }
$commandLine += ' > ' + (Quote-PowerShellLiteral $stdoutPath) + ' 2> ' + (Quote-PowerShellLiteral $stderrPath)
$repoPathForCommandScript = [string]$RepoRoot.Path
$scriptLines = @(
    '$ErrorActionPreference = "Stop"',
    ('Set-Location -LiteralPath "{0}"' -f $repoPathForCommandScript.Replace('"', '`"')),
    $commandLine,
    'exit $LASTEXITCODE'
)
Write-Utf8NoBom -Path $commandScriptPath -Content ($scriptLines -join [Environment]::NewLine)

Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
$taskAction = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument ('-NoProfile -ExecutionPolicy Bypass -File "' + $commandScriptPath + '"') `
    -WorkingDirectory (Get-Location).ProviderPath
$taskTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5)
Register-ScheduledTask -TaskName $taskName -Action $taskAction -Trigger $taskTrigger -User $env:USERNAME -RunLevel Limited -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
Start-Sleep -Seconds 2
$process = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { [string]$_.CommandLine -like "*$commandScriptPath*" } |
    Sort-Object CreationDate -Descending |
    Select-Object -First 1
$processId = if ($process) { [int]$process.ProcessId } else { 0 }

$record = [ordered]@{
    status = "running"
    started_at = (Get-Date).ToUniversalTime().ToString("o")
    pid = $processId
    task_name = $taskName
    launch_method = "scheduled_task"
    run_dir = $runRoot
    stdout_path = $stdoutPath
    stderr_path = $stderrPath
    command_script_path = $commandScriptPath
    no_submit = (-not [bool]$RunLiveSubmit)
    run_live_submit = [bool]$RunLiveSubmit
    confirm_authorized_targets = [bool]$ConfirmAuthorizedTargets
    input_file = $InputFile
    command = "powershell " + $argumentLine
}
Write-Utf8NoBom -Path $recordPath -Content ($record | ConvertTo-Json -Depth 6 -Compress)

Write-Host "REACHOPS_ACCEPTANCE_BACKGROUND_RUN=$runRoot"
Write-Host "ACCEPTANCE_BACKGROUND_RECORD=$recordPath"
Write-Host "ACCEPTANCE_BACKGROUND_TASK=$taskName"
Write-Host "ACCEPTANCE_BACKGROUND_PID=$processId"
