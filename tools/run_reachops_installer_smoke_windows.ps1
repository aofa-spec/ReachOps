param(
    [string]$Root = "",
    [string]$Version = "",
    [string]$InstallDir = "",
    [string]$ReportPath = ""
)

$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
chcp 65001 | Out-Null

if ([string]::IsNullOrWhiteSpace($Root)) {
    $Root = Resolve-Path (Join-Path $PSScriptRoot "..")
} else {
    $Root = Resolve-Path $Root
}
Set-Location $Root

function Read-ReachOpsVersion {
    $versionFile = Join-Path $Root "ReachOps\version.py"
    if (!(Test-Path $versionFile)) {
        throw "ReachOps version file missing: $versionFile"
    }
    $line = Get-Content $versionFile -Encoding UTF8 | Where-Object { $_ -match '^VERSION\s*=' } | Select-Object -First 1
    if (!$line) {
        throw "VERSION not found in $versionFile"
    }
    return (($line -replace '^VERSION\s*=\s*', '') -replace '"', '' -replace "'", '').Trim()
}

if ([string]::IsNullOrWhiteSpace($Version)) {
    $Version = Read-ReachOpsVersion
}

if ([string]::IsNullOrWhiteSpace($InstallDir)) {
    $InstallDir = Join-Path $env:LOCALAPPDATA "Programs\ReachOpsSmoke"
}

if ([string]::IsNullOrWhiteSpace($ReportPath)) {
    $ReportDir = Join-Path $Root "reports\reachops_installer_smoke"
    New-Item -ItemType Directory -Force -Path $ReportDir | Out-Null
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $ReportPath = Join-Path $ReportDir "installer_smoke_$stamp.json"
} else {
    $ReportDir = Split-Path -Parent $ReportPath
    if (![string]::IsNullOrWhiteSpace($ReportDir)) {
        New-Item -ItemType Directory -Force -Path $ReportDir | Out-Null
    }
}

$InstallerPath = Join-Path $Root "dist\installer\ReachOps-Setup-$Version.exe"
$ManifestPath = Join-Path $Root "dist\installer\reachops-update-manifest.json"
$InstallLogPath = Join-Path $Root "reports\reachops_installer_smoke\installer.log"
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $InstallLogPath) | Out-Null

if (!(Test-Path $InstallerPath)) {
    throw "Installer missing: $InstallerPath"
}
if (!(Test-Path $ManifestPath)) {
    throw "Update manifest missing: $ManifestPath"
}

if (Test-Path $InstallDir) {
    Remove-Item -Recurse -Force $InstallDir
}
if (Test-Path $InstallLogPath) {
    Remove-Item -Force $InstallLogPath
}

$installerArgs = @(
    "/VERYSILENT",
    "/SUPPRESSMSGBOXES",
    "/NORESTART",
    "/DIR=$InstallDir",
    "/LOG=$InstallLogPath"
)
$process = Start-Process -FilePath $InstallerPath -ArgumentList $installerArgs -Wait -PassThru
$exePath = Join-Path $InstallDir "ReachOps.exe"
$manifest = Get-Content $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$actualHash = (Get-FileHash $InstallerPath -Algorithm SHA256).Hash.ToLower()
$expectedHash = [string]$manifest.installer.sha256
$runtimePolicy = $manifest.runtime_policy
$preserveConfig = $false
$preserveData = $false
$preserveActivationStatus = $false
if ($null -ne $runtimePolicy) {
    $preserveConfig = [bool]$runtimePolicy.preserve_config
    $preserveData = [bool]$runtimePolicy.preserve_data
    $preserveActivationStatus = [bool]$runtimePolicy.preserve_activation_status
}
$dataInInstallDir = Test-Path (Join-Path $InstallDir "data")

$result = [ordered]@{
    status = "ok"
    installer_exit = [int]$process.ExitCode
    install_dir = $InstallDir
    exe_exists = Test-Path $exePath
    data_in_install_dir = $dataInInstallDir
    manifest_exists = Test-Path $ManifestPath
    manifest_version = [string]$manifest.version
    manifest_build = [string]$manifest.build
    installer_size = (Get-Item $InstallerPath).Length
    hash_ok = ($actualHash -eq $expectedHash.ToLower())
    preserve_config = $preserveConfig
    preserve_data = $preserveData
    preserve_activation_status = $preserveActivationStatus
    install_log = $InstallLogPath
    report_path = $ReportPath
}

$failures = @()
if ($process.ExitCode -ne 0) { $failures += "installer_exit" }
if (!$result.exe_exists) { $failures += "exe_missing" }
if ($dataInInstallDir) { $failures += "data_written_to_install_dir" }
if (!$result.hash_ok) { $failures += "manifest_hash_mismatch" }
if (!$preserveConfig) { $failures += "manifest_preserve_config_missing" }
if (!$preserveData) { $failures += "manifest_preserve_data_missing" }
if (!$preserveActivationStatus) { $failures += "manifest_preserve_activation_status_missing" }

if ($failures.Count -gt 0) {
    $result.status = "failed"
    $result.failures = $failures
}

$json = $result | ConvertTo-Json -Compress
[System.IO.File]::WriteAllText($ReportPath, $json, [System.Text.UTF8Encoding]::new($false))
Write-Output $json

if ($result.status -ne "ok") {
    exit 1
}
