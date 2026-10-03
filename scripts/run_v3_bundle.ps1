param(
    [switch]$KeepBridge
)

$ErrorActionPreference = "Stop"

$AppRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BundleRoot = (Resolve-Path (Join-Path $AppRoot "..")).Path
$BridgeUrl = "http://127.0.0.1:8765"
$HealthUrl = "$BridgeUrl/health"
$BridgeScript = Join-Path $AppRoot "scripts\run_v3_bridge.py"
$ServerFile = Join-Path $AppRoot "desktop_bridge\server.py"
$GodotProjectDir = Join-Path $AppRoot "godot_client"
$GodotExe = Join-Path $BundleRoot "runtime\godot\Godot_v4.0-stable_win64.exe"
$RuntimeDir = Join-Path $AppRoot "outputs\runtime"
$BridgeStdout = Join-Path $RuntimeDir "v3_desktop_bridge_stdout.log"
$BridgeStderr = Join-Path $RuntimeDir "v3_desktop_bridge_stderr.log"
$ProtectedV2 = Join-Path $RuntimeDir "franchise_mode_checkpoint_v1.pkl.gz"
$WorkingV3 = Join-Path $RuntimeDir "v3_godot_working_checkpoint.pkl.gz"

New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null

function Get-ExpectedApiVersion {
    $serverText = Get-Content $ServerFile -Raw
    $match = [regex]::Match($serverText, 'API_VERSION\s*=\s*"([^"]+)"')
    if (-not $match.Success) {
        throw "Could not determine API_VERSION from packaged desktop_bridge/server.py."
    }
    return $match.Groups[1].Value
}

function Resolve-BundlePython {
    $candidates = @(
        (Join-Path $BundleRoot "runtime\python\python.exe"),
        (Join-Path $BundleRoot "runtime\venv\Scripts\python.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate -PathType Leaf) {
            return (Resolve-Path $candidate).Path
        }
    }

    if ($env:CONDA_DEFAULT_ENV -eq "nba-roster-optimizer") {
        $activePython = (Get-Command python -ErrorAction SilentlyContinue).Source
        if ($activePython -and (Test-Path $activePython -PathType Leaf)) {
            return $activePython
        }
    }

    $knownConda = Join-Path $env:USERPROFILE "miniconda3\envs\nba-roster-optimizer\python.exe"
    if (Test-Path $knownConda -PathType Leaf) {
        return $knownConda
    }

    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand -and (Test-Path $pythonCommand.Source -PathType Leaf)) {
        return $pythonCommand.Source
    }

    throw "No usable Python runtime was found. Run Setup_Runtime.cmd once, then relaunch."
}

function Get-BridgeHealth {
    try {
        return Invoke-RestMethod $HealthUrl -TimeoutSec 2
    } catch {
        return $null
    }
}

function Warm-DesktopViews {
    $paths = @(
        "/v3/franchise-summary",
        "/v3/roster",
        "/v3/game-day",
        "/v3/preferences",
        "/v3/saves"
    )
    $warmed = 0
    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    foreach ($path in $paths) {
        try {
            Invoke-RestMethod "$BridgeUrl$path" -TimeoutSec 30 | Out-Null
            $warmed += 1
        } catch {
            Write-Host "[WARN] Warm-up skipped $path : $($_.Exception.Message)" -ForegroundColor Yellow
        }
    }
    $timer.Stop()
    Write-Host ("[WARM] Prepared {0}/{1} core views in {2:N0} ms." -f $warmed, $paths.Count, $timer.Elapsed.TotalMilliseconds) -ForegroundColor DarkCyan
}

if (-not (Test-Path $GodotExe -PathType Leaf)) {
    throw "Bundled Godot runtime is missing: $GodotExe"
}
if (-not (Test-Path $ProtectedV2 -PathType Leaf)) {
    throw "Protected V2 checkpoint is missing from the bundle: $ProtectedV2"
}

if (-not (Test-Path $WorkingV3 -PathType Leaf)) {
    Copy-Item $ProtectedV2 $WorkingV3 -Force
    Write-Host "[INIT] Created an isolated V3 working checkpoint from the bundled protected V2 checkpoint." -ForegroundColor DarkCyan
}

$ExpectedApiVersion = Get-ExpectedApiVersion
$BridgeProcess = $null
$StartedBridge = $false

Write-Host ""
Write-Host "=== NBA FRANCHISE SIMULATOR V3 ===" -ForegroundColor Cyan
Write-Host "Bundle root: $BundleRoot"
Write-Host "Expected bridge API: $ExpectedApiVersion"

try {
    $health = Get-BridgeHealth
    if ($health) {
        if ($health.service -ne "nba-franchise-v3-bridge") {
            throw "Port 8765 is occupied by an unexpected service."
        }
        if ($health.api_version -ne $ExpectedApiVersion) {
            throw "A stale V3 bridge is running on API $($health.api_version); bundle expects $ExpectedApiVersion."
        }
        Write-Host "[OK] Existing bridge detected on API $($health.api_version)." -ForegroundColor Green
    } else {
        $listener = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
        if ($listener) {
            throw "Port 8765 is occupied, but the V3 bridge is not responding."
        }

        $python = Resolve-BundlePython
        Write-Host "[START] Launching bundled V3 bridge with $python"
        Remove-Item $BridgeStdout, $BridgeStderr -Force -ErrorAction SilentlyContinue

        $BridgeProcess = Start-Process `
            -FilePath $python `
            -ArgumentList @("`"$BridgeScript`"") `
            -WorkingDirectory $AppRoot `
            -RedirectStandardOutput $BridgeStdout `
            -RedirectStandardError $BridgeStderr `
            -WindowStyle Hidden `
            -PassThru
        $StartedBridge = $true

        $deadline = (Get-Date).AddSeconds(25)
        do {
            Start-Sleep -Milliseconds 350
            if ($BridgeProcess.HasExited) {
                $stderr = if (Test-Path $BridgeStderr) { Get-Content $BridgeStderr -Raw } else { "" }
                throw "Bundled V3 bridge exited during startup.`n$stderr"
            }
            $health = Get-BridgeHealth
        } until ($health -or (Get-Date) -ge $deadline)

        if (-not $health) {
            throw "Timed out waiting for the bundled V3 bridge."
        }
        if ($health.api_version -ne $ExpectedApiVersion) {
            throw "Bundled bridge started on API $($health.api_version), expected $ExpectedApiVersion."
        }
        Write-Host "[OK] Bundled bridge healthy on API $($health.api_version)." -ForegroundColor Green
    }

    Warm-DesktopViews

    Write-Host "[START] Launching packaged Godot client..."
    $GodotProcess = Start-Process `
        -FilePath $GodotExe `
        -ArgumentList @("--path", "`"$GodotProjectDir`"") `
        -WorkingDirectory $BundleRoot `
        -PassThru

    Write-Host "[READY] NBA Franchise Simulator V3 is running." -ForegroundColor Green
    Wait-Process -Id $GodotProcess.Id
}
finally {
    if ($StartedBridge -and -not $KeepBridge -and $BridgeProcess -and -not $BridgeProcess.HasExited) {
        Write-Host "[STOP] Shutting down bundle-owned bridge..."
        Stop-Process -Id $BridgeProcess.Id -Force -ErrorAction SilentlyContinue
        try {
            Wait-Process -Id $BridgeProcess.Id -Timeout 3 -ErrorAction SilentlyContinue
        } catch {
        }
    } elseif ($StartedBridge -and $KeepBridge) {
        Write-Host "[KEEP] Bundle-owned bridge left running by request."
    } else {
        Write-Host "[INFO] Existing bridge was not owned by this launcher and was left untouched."
    }
    Write-Host "V3 desktop session ended."
}
