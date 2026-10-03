param(
    [string]$OutputRoot = "",
    [string]$GodotPath = "",
    [switch]$IncludeCurrentSave,
    [switch]$PlanOnly,
    [double]$MaxBundleGB = 4.0
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ExpectedBranch = "v3-godot-desktop"
$BundleName = "NBA_Franchise_Simulator_V3"
$DefaultOutputRoot = Join-Path $RepoRoot "dist_v3"

if (-not $OutputRoot) {
    $OutputRoot = $DefaultOutputRoot
}

function Resolve-GodotExecutable {
    param([string]$RequestedPath)

    if ($RequestedPath -and (Test-Path $RequestedPath -PathType Leaf)) {
        return (Resolve-Path $RequestedPath).Path
    }

    $knownPaths = @(
        (Join-Path $env:USERPROFILE "Downloads\Godot_v4.0-stable_win64.exe"),
        (Join-Path $env:USERPROFILE "Downloads\Godot_v4.0-stable_win64\Godot_v4.0-stable_win64.exe")
    )

    foreach ($candidate in $knownPaths) {
        if (Test-Path $candidate -PathType Leaf) {
            return (Resolve-Path $candidate).Path
        }
    }

    foreach ($name in @("godot", "godot4", "Godot_v4.0-stable_win64.exe")) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command -and (Test-Path $command.Source -PathType Leaf)) {
            return $command.Source
        }
    }

    throw "Could not locate Godot. Re-run with -GodotPath 'C:\path\to\Godot.exe'."
}

function Get-ApiVersion {
    $serverFile = Join-Path $RepoRoot "desktop_bridge\server.py"
    $serverText = Get-Content $serverFile -Raw
    $match = [regex]::Match($serverText, 'API_VERSION\s*=\s*"([^"]+)"')
    if (-not $match.Success) {
        throw "Could not determine API_VERSION from desktop_bridge/server.py."
    }
    return $match.Groups[1].Value
}

function Copy-Tree {
    param(
        [string]$Source,
        [string]$Destination
    )

    if (-not (Test-Path $Source)) {
        return
    }

    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    $null = robocopy $Source $Destination /E /NFL /NDL /NJH /NJS /NP /XD `
        ".git" ".pytest_cache" "__pycache__" "backups" "dist_v3" ".v3_runtime"
    if ($LASTEXITCODE -ge 8) {
        throw "robocopy failed while copying $Source (exit $LASTEXITCODE)."
    }
}

function Copy-OptionalFile {
    param(
        [string]$Source,
        [string]$Destination
    )
    if (Test-Path $Source -PathType Leaf) {
        New-Item -ItemType Directory -Force -Path (Split-Path $Destination -Parent) | Out-Null
        Copy-Item $Source $Destination -Force
    }
}

function Get-DirectoryBytes {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        return [int64]0
    }
    $sum = (
        Get-ChildItem $Path -Recurse -File -ErrorAction SilentlyContinue |
        Measure-Object Length -Sum
    ).Sum
    if ($null -eq $sum) {
        return [int64]0
    }
    return [int64]$sum
}

$branch = (& git -C $RepoRoot branch --show-current).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Unable to determine Git branch."
}
if ($branch -ne $ExpectedBranch) {
    throw "Expected branch '$ExpectedBranch', found '$branch'."
}

$head = (& git -C $RepoRoot rev-parse --short HEAD).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Unable to determine Git HEAD."
}

$status = (& git -C $RepoRoot status --porcelain)
if ($LASTEXITCODE -ne 0) {
    throw "Unable to determine Git status."
}
if ($status) {
    throw "Working tree must be clean before creating a distributable bundle."
}

$GodotExe = Resolve-GodotExecutable -RequestedPath $GodotPath
$ApiVersion = Get-ApiVersion

$RepoRuntime = Join-Path $RepoRoot "outputs\runtime"
$ProtectedV2 = Join-Path $RepoRuntime "franchise_mode_checkpoint_v1.pkl.gz"
$ProtectedV2Backup = Join-Path $RepoRuntime "franchise_mode_checkpoint_v1.backup.pkl.gz"
$CurrentV3 = Join-Path $RepoRuntime "v3_godot_working_checkpoint.pkl.gz"
$CurrentV3Backup = Join-Path $RepoRuntime "v3_godot_working_checkpoint.pkl.gz.backup"
$SaveManager = Join-Path $RepoRuntime "v3_save_manager"
$Preferences = Join-Path $RepoRuntime "v3_desktop_preferences.json"

if (-not (Test-Path $ProtectedV2 -PathType Leaf)) {
    throw "Protected V2 checkpoint is missing: $ProtectedV2"
}

Write-Host ""
Write-Host "=== V3 WINDOWS BUNDLE PLAN ===" -ForegroundColor Cyan
Write-Host "Source branch : $branch"
Write-Host "Source HEAD   : $head"
Write-Host "Bridge API    : $ApiVersion"
Write-Host "Godot         : $GodotExe"
Write-Host "Output root   : $OutputRoot"
Write-Host "Current save  : $($IncludeCurrentSave.IsPresent)"
Write-Host "Size ceiling  : $MaxBundleGB GB"

if ($PlanOnly) {
    Write-Host "[PLAN] Packaging prerequisites are available. No files were written." -ForegroundColor Green
    exit 0
}

$BundleRoot = Join-Path $OutputRoot $BundleName
$AppRoot = Join-Path $BundleRoot "app"
$RuntimeRoot = Join-Path $BundleRoot "runtime"
$GodotRuntime = Join-Path $RuntimeRoot "godot"
$BundleGodot = Join-Path $GodotRuntime "Godot_v4.0-stable_win64.exe"
$BundleAppRuntime = Join-Path $AppRoot "outputs\runtime"

if (Test-Path $BundleRoot) {
    Remove-Item $BundleRoot -Recurse -Force
}

New-Item -ItemType Directory -Force -Path $AppRoot, $GodotRuntime, $BundleAppRuntime | Out-Null

# Application source/data only. Development outputs are intentionally NOT copied.
$sourceDirs = @(
    "app_data",
    "assets",
    "data",
    "desktop_bridge",
    "docs",
    "godot_client",
    "models",
    "src"
)

foreach ($relative in $sourceDirs) {
    $source = Join-Path $RepoRoot $relative
    if (Test-Path $source) {
        Copy-Tree -Source $source -Destination (Join-Path $AppRoot $relative)
    }
}

New-Item -ItemType Directory -Force -Path (Join-Path $AppRoot "scripts") | Out-Null
Copy-Item (Join-Path $RepoRoot "scripts\run_v3_bridge.py") (Join-Path $AppRoot "scripts\run_v3_bridge.py") -Force
Copy-Item (Join-Path $RepoRoot "requirements.txt") (Join-Path $AppRoot "requirements.txt") -Force

# Minimal runtime seed. This is the only outputs artifact required by a fresh tester build.
Copy-Item $ProtectedV2 (Join-Path $BundleAppRuntime "franchise_mode_checkpoint_v1.pkl.gz") -Force
Copy-OptionalFile `
    -Source $ProtectedV2Backup `
    -Destination (Join-Path $BundleAppRuntime "franchise_mode_checkpoint_v1.backup.pkl.gz")

# Creator-save packaging is explicit and opt-in.
if ($IncludeCurrentSave) {
    if (-not (Test-Path $CurrentV3 -PathType Leaf)) {
        throw "-IncludeCurrentSave was requested, but the current V3 working checkpoint is missing."
    }

    Copy-Item $CurrentV3 (Join-Path $BundleAppRuntime "v3_godot_working_checkpoint.pkl.gz") -Force
    Copy-OptionalFile `
        -Source $CurrentV3Backup `
        -Destination (Join-Path $BundleAppRuntime "v3_godot_working_checkpoint.pkl.gz.backup")

    if (Test-Path $SaveManager) {
        Copy-Tree -Source $SaveManager -Destination (Join-Path $BundleAppRuntime "v3_save_manager")
    }
    Copy-OptionalFile `
        -Source $Preferences `
        -Destination (Join-Path $BundleAppRuntime "v3_desktop_preferences.json")
}

Copy-Item $GodotExe $BundleGodot -Force
Copy-Item (Join-Path $RepoRoot "scripts\run_v3_bundle.ps1") (Join-Path $AppRoot "scripts\run_v3_bundle.ps1") -Force
Copy-Item (Join-Path $RepoRoot "scripts\bootstrap_v3_bundle_runtime.ps1") (Join-Path $AppRoot "scripts\bootstrap_v3_bundle_runtime.ps1") -Force

$startCmd = @'
@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\app\scripts\run_v3_bundle.ps1"
if errorlevel 1 (
    echo.
    echo NBA Franchise Simulator V3 exited with an error.
    pause
)
'@
$startCmd | Set-Content -Path (Join-Path $BundleRoot "Start_NBA_Franchise_Simulator_V3.cmd") -Encoding ASCII

$setupCmd = @'
@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\app\scripts\bootstrap_v3_bundle_runtime.ps1"
if errorlevel 1 (
    echo.
    echo Runtime setup exited with an error.
    pause
)
'@
$setupCmd | Set-Content -Path (Join-Path $BundleRoot "Setup_Runtime.cmd") -Encoding ASCII

$testerReadme = @"
NBA FRANCHISE SIMULATOR V3 - WINDOWS TEST BUNDLE
=================================================

1. Make sure no development copy of the V3 bridge is running.
2. Double-click Start_NBA_Franchise_Simulator_V3.cmd.
3. If it reports that Python is unavailable, double-click Setup_Runtime.cmd once.
4. After setup completes, launch the game again.

Setup_Runtime creates a Python environment inside THIS bundle. If Python 3.12
is not installed and Windows Package Manager (winget) is available, setup can
install Python 3.12 for the current Windows user.

This bundle already contains the Godot runtime used by the project.

Source branch: $branch
Source commit: $head
Bridge API: $ApiVersion
Built UTC: $([DateTime]::UtcNow.ToString("o"))
Includes creator current V3 save: $($IncludeCurrentSave.IsPresent)

The packaged launcher requires exclusive ownership of port 8765. It will not
reuse a bridge from the development repository or another V3 package.
"@
$testerReadme | Set-Content -Path (Join-Path $BundleRoot "README_TESTER.txt") -Encoding UTF8

$manifestPath = Join-Path $BundleRoot "BUILD_MANIFEST.json"
$manifest = [ordered]@{
    bundle_version = "v3-windows-bundle-batch-18d1-v1.1.0-2026-10-03"
    source_branch = $branch
    source_commit = $head
    bridge_api = $ApiVersion
    built_utc = [DateTime]::UtcNow.ToString("o")
    include_current_save = $IncludeCurrentSave.IsPresent
    godot_runtime = "runtime/godot/Godot_v4.0-stable_win64.exe"
    app_root = "app"
    launcher = "Start_NBA_Franchise_Simulator_V3.cmd"
    runtime_setup = "Setup_Runtime.cmd"
    outputs_policy = "minimal-runtime-seed-only"
    max_bundle_gb = $MaxBundleGB
    bundle_bytes = 0
    bundle_mb = 0
    bundle_gb = 0
}
$manifest | ConvertTo-Json -Depth 4 | Set-Content -Path $manifestPath -Encoding UTF8

$bundleBytes = Get-DirectoryBytes -Path $BundleRoot
$bundleGB = [math]::Round($bundleBytes / 1GB, 3)
$bundleMB = [math]::Round($bundleBytes / 1MB, 1)

$manifest.bundle_bytes = $bundleBytes
$manifest.bundle_mb = $bundleMB
$manifest.bundle_gb = $bundleGB
$manifest | ConvertTo-Json -Depth 4 | Set-Content -Path $manifestPath -Encoding UTF8

if ($bundleGB -gt $MaxBundleGB) {
    throw "Bundle size $bundleGB GB exceeds the safety ceiling of $MaxBundleGB GB. Inspect the package before distribution."
}

Write-Host ""
Write-Host "[PASS] V3 Windows test bundle created." -ForegroundColor Green
Write-Host "Bundle: $BundleRoot"
Write-Host ("Size: {0:N1} MB ({1:N3} GB)" -f $bundleMB, $bundleGB)
Write-Host "Launcher: $(Join-Path $BundleRoot 'Start_NBA_Franchise_Simulator_V3.cmd')"
Write-Host "Setup: $(Join-Path $BundleRoot 'Setup_Runtime.cmd')"
Write-Host ""
Write-Host "Development outputs were excluded. The generated dist_v3 folder remains ignored by Git."
