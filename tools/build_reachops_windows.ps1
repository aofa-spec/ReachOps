param(
    [string]$Python = "python",
    [string]$Version = "",
    [string]$Build = "0",
    [switch]$SkipTests,
    [switch]$SkipInstaller,
    [switch]$SkipInstallerSmoke
)

$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 | Out-Null
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

function Assert-LastExitCode {
    param([string]$StepName)
    if ($LASTEXITCODE -ne 0) {
        throw "$StepName failed with exit code $LASTEXITCODE"
    }
}

function Read-ReachOpsVersion {
    $code = "from ReachOps.version import VERSION; print(VERSION)"
    return (& $Python -c $code).Trim()
}

function Resolve-VersionInfoBuild {
    param([string]$BuildValue)
    $digits = @([regex]::Matches([string]$BuildValue, "\d+") | ForEach-Object { $_.Value })
    if ($digits.Count -gt 0) {
        $number = [int64]$digits[$digits.Count - 1]
        if ($number -le 65535) {
            return [string]$number
        }
        $normalized = $number % 65535
        if ($normalized -eq 0) {
            return "65535"
        }
        return [string]$normalized
    }
    return "0"
}

function Find-InnoSetupCompiler {
    $command = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
    if ($null -ne $command) {
        return $command.Source
    }
    $candidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) {
            return $candidate
        }
    }
    return ""
}

if ([string]::IsNullOrWhiteSpace($Version)) {
    $Version = Read-ReachOpsVersion
}

$VenvDir = Join-Path $Root ".venv-reachops-build"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$ReachOpsRequirements = Join-Path $Root "ReachOps\packaging\requirements-reachops.txt"
$FallbackRequirements = Join-Path $Root "requirements.txt"

Write-Host "ReachOps Windows build"
Write-Host "Root: $Root"
Write-Host "Version: $Version"
Write-Host "Build: $Build"
$VersionInfoBuild = Resolve-VersionInfoBuild $Build
Write-Host "VersionInfoBuild: $VersionInfoBuild"

if (!(Test-Path $VenvPython)) {
    & $Python -m venv $VenvDir
    Assert-LastExitCode "Create ReachOps build venv"
}

& $VenvPython -m pip install --upgrade pip setuptools wheel
Assert-LastExitCode "Install build bootstrap dependencies"
if (Test-Path $ReachOpsRequirements) {
    Write-Host "Installing ReachOps standalone requirements: $ReachOpsRequirements"
    & $VenvPython -m pip install -r $ReachOpsRequirements
    Assert-LastExitCode "Install ReachOps standalone requirements"
} elseif (Test-Path $FallbackRequirements) {
    Write-Warning "ReachOps standalone requirements not found. Falling back to root requirements.txt."
    & $VenvPython -m pip install -r $FallbackRequirements
    Assert-LastExitCode "Install fallback requirements"
} else {
    throw "No requirements file found for ReachOps build."
}

if (!$SkipTests) {
    & $VenvPython -m py_compile ReachOpsApp.py GrowthIntelligenceApp.py ReachOps\launcher.py ReachOps\workbench\standalone_app.py ReachOps\intelligence\service.py
    Assert-LastExitCode "ReachOps build py_compile"
    & $VenvPython tools\reachops_delivery_smoke.py --json
    Assert-LastExitCode "ReachOps delivery smoke"
    & $VenvPython tools\reachops_delivery_audit.py --json
    Assert-LastExitCode "ReachOps delivery audit"
    & $VenvPython -m unittest tests.test_reachops_campaign
    Assert-LastExitCode "ReachOps campaign tests"
}

& $VenvPython -m PyInstaller --clean --noconfirm ReachOps\packaging\reachops.spec
Assert-LastExitCode "ReachOps PyInstaller build"

$ExePath = Join-Path $Root "dist\ReachOps\ReachOps.exe"
if (!(Test-Path $ExePath)) {
    throw "PyInstaller output missing: $ExePath"
}

Write-Host "Built: $ExePath"

if (!$SkipInstaller) {
    $iscc = Find-InnoSetupCompiler
    if ([string]::IsNullOrWhiteSpace($iscc)) {
        Write-Warning "ISCC.exe not found. Skipping installer. Install Inno Setup or pass -SkipInstaller."
    } else {
        & $iscc "ReachOps\packaging\ReachOps.iss" "/DMyAppVersion=$Version" "/DMyAppBuild=$Build" "/DMyVersionInfoBuild=$VersionInfoBuild"
        Assert-LastExitCode "ReachOps Inno Setup installer"
        $InstallerPath = Join-Path $Root "dist\installer\ReachOps-Setup-$Version.exe"
        if (Test-Path $InstallerPath) {
            & $VenvPython tools\write_reachops_update_manifest.py --installer $InstallerPath --version $Version --build $Build
            Assert-LastExitCode "ReachOps update manifest"
            Write-Host "Installer: $InstallerPath"
            if (!$SkipInstallerSmoke) {
                powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File tools\run_reachops_installer_smoke_windows.ps1 -Root $Root -Version $Version
                Assert-LastExitCode "ReachOps installer smoke"
            }
        } else {
            throw "Installer output missing: $InstallerPath"
        }
    }
}

Write-Host "ReachOps build completed."
