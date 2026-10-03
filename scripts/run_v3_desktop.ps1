param(
    [string]$GodotPath = "",
    [switch]$KeepBridge,
    [switch]$RunGate
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BridgeUrl = "http://127.0.0.1:8765"
$HealthUrl = "$BridgeUrl/health"
$BridgeScript = Join-Path $RepoRoot "scripts\run_v3_bridge.py"
$ServerFile = Join-Path $RepoRoot "desktop_bridge\server.py"
$GodotProjectDir = Join-Path $RepoRoot "godot_client"
$RuntimeDir = Join-Path $RepoRoot "outputs\runtime"
$BridgeStdout = Join-Path $RuntimeDir "v3_desktop_bridge_stdout.log"
$BridgeStderr = Join-Path $RuntimeDir "v3_desktop_bridge_stderr.log"

New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null

function Get-ExpectedApiVersion {
    $serverText = Get-Content $ServerFile -Raw
    $match = [regex]::Match($serverText, 'API_VERSION\s*=\s*"([^"]+)"')
    if (-not $match.Success) {
        throw "Could not determine API_VERSION from desktop_bridge/server.py"
    }
    return $match.Groups[1].Value
}

function Get-BridgeHealth {
    try {
        return Invoke-RestMethod $HealthUrl -TimeoutSec 2
    } catch {
        return $null
    }
}

function Warm-V3DesktopReadCache {
    param([string]$BaseUrl)

    $warmPaths = @(
        "/v3/franchise-summary",
        "/v3/roster",
        "/v3/game-day",
        "/v3/preferences",
        "/v3/saves"
    )
    $warmed = 0
    $timer = [System.Diagnostics.Stopwatch]::StartNew()

    foreach ($path in $warmPaths) {
        try {
            Invoke-RestMethod "$BaseUrl$path" -TimeoutSec 30 | Out-Null
            $warmed += 1
        } catch {
            Write-Host "[WARN] Cache warm-up skipped $path : $($_.Exception.Message)" -ForegroundColor Yellow
        }
    }

    $timer.Stop()
    Write-Host ("[WARM] Prepared {0}/{1} core desktop views in {2:N0} ms." -f $warmed, $warmPaths.Count, $timer.Elapsed.TotalMilliseconds) -ForegroundColor DarkCyan
}

function Resolve-V3Python {
    if ($env:CONDA_DEFAULT_ENV -eq "nba-roster-optimizer") {
        $activePython = (Get-Command python -ErrorAction SilentlyContinue).Source
        if ($activePython -and (Test-Path $activePython)) {
            return $activePython
        }
    }

    $knownPython = Join-Path $env:USERPROFILE "miniconda3\envs\nba-roster-optimizer\python.exe"
    if (Test-Path $knownPython) {
        return $knownPython
    }

    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        return $pythonCommand.Source
    }

    throw "Could not locate Python for the nba-roster-optimizer environment."
}

function Resolve-GodotExecutable {
    param([string]$RequestedPath)

    if ($RequestedPath -and (Test-Path $RequestedPath)) {
        return (Resolve-Path $RequestedPath).Path
    }

    $knownPaths = @(
        (Join-Path $env:USERPROFILE "Downloads\Godot_v4.0-stable_win64.exe\Godot_v4.0-stable_win64.exe"),
        (Join-Path $env:USERPROFILE "Downloads\Godot_v4.0-stable_win64.exe"),
        (Join-Path $env:USERPROFILE "Downloads\Godot_v4.0-stable_win64\Godot_v4.0-stable_win64.exe")
    )

    foreach ($candidate in $knownPaths) {
        if (Test-Path $candidate) {
            return (Resolve-Path $candidate).Path
        }
    }

    foreach ($name in @("godot", "godot4", "Godot_v4.0-stable_win64.exe")) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command) {
            return $command.Source
        }
    }

    throw "Could not locate Godot. Re-run with -GodotPath 'C:\path\to\Godot.exe'."
}

$ExpectedApiVersion = Get-ExpectedApiVersion
$BridgeProcess = $null
$StartedBridge = $false

Write-Host ""
Write-Host "=== NBA FRANCHISE SIMULATOR V3 DESKTOP ===" -ForegroundColor Cyan
Write-Host "Expected bridge API: $ExpectedApiVersion"

try {
    $health = Get-BridgeHealth

    if ($health) {
        if ($health.service -ne "nba-franchise-v3-bridge") {
            throw "Port 8765 is occupied by an unexpected service. Refusing to launch."
        }
        if ($health.api_version -ne $ExpectedApiVersion) {
            throw "A stale V3 bridge is already running (API $($health.api_version)); source expects $ExpectedApiVersion. Stop it and relaunch."
        }

        Write-Host "[OK] Existing V3 bridge detected on API $($health.api_version)." -ForegroundColor Green
    } else {
        $listener = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
        if ($listener) {
            throw "Port 8765 is already occupied, but it is not responding as the V3 bridge."
        }

        $python = Resolve-V3Python
        Write-Host "[START] Launching V3 bridge with $python"

        Remove-Item $BridgeStdout, $BridgeStderr -Force -ErrorAction SilentlyContinue

        $BridgeProcess = Start-Process `
            -FilePath $python `
            -ArgumentList @("`"$BridgeScript`"") `
            -WorkingDirectory $RepoRoot `
            -RedirectStandardOutput $BridgeStdout `
            -RedirectStandardError $BridgeStderr `
            -WindowStyle Hidden `
            -PassThru

        $StartedBridge = $true

        $deadline = (Get-Date).AddSeconds(20)
        do {
            Start-Sleep -Milliseconds 350

            if ($BridgeProcess.HasExited) {
                $stderr = if (Test-Path $BridgeStderr) { Get-Content $BridgeStderr -Raw } else { "" }
                throw "The V3 bridge exited during startup.`n$stderr"
            }

            $health = Get-BridgeHealth
        } until ($health -or (Get-Date) -ge $deadline)

        if (-not $health) {
            throw "Timed out waiting for the V3 bridge to become healthy."
        }

        if ($health.api_version -ne $ExpectedApiVersion) {
            throw "Bridge started on API $($health.api_version), but source expects $ExpectedApiVersion."
        }

        Write-Host "[OK] V3 bridge healthy on API $($health.api_version)." -ForegroundColor Green
    }

    if ($RunGate) {
        Write-Host "[CHECK] Running V3 quick gate..."
        & (Join-Path $RepoRoot "scripts\v3_quick_gate.ps1") -RequireBridge
        if ($LASTEXITCODE -ne 0) {
            throw "V3 quick gate failed. Godot was not launched."
        }
    }

    Warm-V3DesktopReadCache -BaseUrl $BridgeUrl

    $ResolvedGodot = Resolve-GodotExecutable -RequestedPath $GodotPath
    Write-Host "[START] Launching Godot desktop client..."
    Write-Host "        $ResolvedGodot"

    $GodotProcess = Start-Process `
        -FilePath $ResolvedGodot `
        -ArgumentList @("--path", "`"$GodotProjectDir`"") `
        -WorkingDirectory $RepoRoot `
        -PassThru

    Write-Host "[READY] V3 desktop is running." -ForegroundColor Green
    Write-Host "Close the game window to return here."

    Wait-Process -Id $GodotProcess.Id
}
finally {
    if ($StartedBridge -and -not $KeepBridge -and $BridgeProcess -and -not $BridgeProcess.HasExited) {
        Write-Host "[STOP] Shutting down launcher-owned V3 bridge..."
        Stop-Process -Id $BridgeProcess.Id -Force -ErrorAction SilentlyContinue
        try {
            Wait-Process -Id $BridgeProcess.Id -Timeout 3 -ErrorAction SilentlyContinue
        } catch {
        }
    } elseif ($StartedBridge -and $KeepBridge) {
        Write-Host "[KEEP] V3 bridge left running by request."
    } else {
        Write-Host "[INFO] Existing bridge was not owned by this launcher and was left untouched."
    }

    Write-Host "V3 desktop session ended."
}
