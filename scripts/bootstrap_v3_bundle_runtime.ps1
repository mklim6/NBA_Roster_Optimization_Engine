param(
    [switch]$ForceRebuild,
    [switch]$NoWinget
)

$ErrorActionPreference = "Stop"

$AppRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BundleRoot = (Resolve-Path (Join-Path $AppRoot "..")).Path
$VenvRoot = Join-Path $BundleRoot "runtime\venv"
$VenvPython = Join-Path $VenvRoot "Scripts\python.exe"
$Requirements = Join-Path $AppRoot "requirements.txt"
$ProtectedV2 = Join-Path $AppRoot "outputs\runtime\franchise_mode_checkpoint_v1.pkl.gz"

function Find-BasePython {
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        try {
            $candidate = (& py -3.12 -c "import sys; print(sys.executable)" 2>$null).Trim()
            if ($candidate -and (Test-Path $candidate -PathType Leaf)) {
                return $candidate
            }
        } catch {
        }
    }

    if ($env:CONDA_DEFAULT_ENV -eq "nba-roster-optimizer") {
        $active = (Get-Command python -ErrorAction SilentlyContinue).Source
        if ($active -and (Test-Path $active -PathType Leaf)) {
            return $active
        }
    }

    $knownConda = Join-Path $env:USERPROFILE "miniconda3\envs\nba-roster-optimizer\python.exe"
    if (Test-Path $knownConda -PathType Leaf) {
        return $knownConda
    }

    $normal = Get-Command python -ErrorAction SilentlyContinue
    if ($normal -and (Test-Path $normal.Source -PathType Leaf)) {
        return $normal.Source
    }

    return $null
}

function Resolve-BasePython {
    $candidate = Find-BasePython
    if ($candidate) {
        return $candidate
    }

    if (-not $NoWinget) {
        $winget = Get-Command winget -ErrorAction SilentlyContinue
        if ($winget) {
            Write-Host "[SETUP] Python 3.12 was not found. Installing Python.Python.3.12 for the current user with winget..." -ForegroundColor Yellow
            & winget install `
                --exact `
                --id Python.Python.3.12 `
                --scope user `
                --accept-package-agreements `
                --accept-source-agreements `
                --silent

            if ($LASTEXITCODE -eq 0) {
                $candidate = Find-BasePython
                if ($candidate) {
                    return $candidate
                }

                $pythonRoot = Join-Path $env:LOCALAPPDATA "Programs\Python"
                if (Test-Path $pythonRoot) {
                    $knownUserPython = Get-ChildItem `
                        $pythonRoot `
                        -Filter python.exe `
                        -Recurse `
                        -File `
                        -ErrorAction SilentlyContinue |
                        Sort-Object FullName -Descending |
                        Select-Object -First 1

                    if ($knownUserPython) {
                        return $knownUserPython.FullName
                    }
                }
            }
        }
    }

    throw "Python 3.12 is unavailable. Install 64-bit Python 3.12, then run Setup_Runtime.cmd again."
}

function Test-BundleRuntime {
    param([string]$PythonExe)

    $smoke = "import sys; from pathlib import Path; root=Path(r'$AppRoot'); sys.path.insert(0,str(root)); sys.path.insert(0,str(root/'src')); import starlette,uvicorn,cloudpickle; from desktop_bridge import server; from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint; from freeform_trade_machine_engine_v3 import load_runtime_data; cp=load_franchise_checkpoint(path=Path(r'$ProtectedV2'),allow_backup=False); assert cp is not None; runtime=load_runtime_data(); assert runtime is not None; assert server.API_VERSION=='0.18.1'; print('Bundle-local V3 server/checkpoint smoke: PASS'); print('Bundle-local V3 transaction runtime-data smoke: PASS')"
    & $PythonExe -c $smoke
    if ($LASTEXITCODE -ne 0) {
        throw "Bundle-local runtime smoke test failed."
    }
}

if (-not (Test-Path $Requirements -PathType Leaf)) {
    throw "requirements.txt is missing from the application bundle."
}
if (-not (Test-Path $ProtectedV2 -PathType Leaf)) {
    throw "The protected V2 bootstrap checkpoint is missing from the application bundle."
}

if ($ForceRebuild -and (Test-Path $VenvRoot)) {
    Write-Host "[RESET] Removing existing bundle-local Python environment..."
    Remove-Item $VenvRoot -Recurse -Force
}

if (Test-Path $VenvPython -PathType Leaf) {
    Write-Host "[OK] Bundle-local Python runtime already exists: $VenvPython" -ForegroundColor Green
    Test-BundleRuntime -PythonExe $VenvPython
    exit 0
}

$BasePython = Resolve-BasePython
Write-Host ""
Write-Host "=== NBA FRANCHISE SIMULATOR V3 RUNTIME SETUP ===" -ForegroundColor Cyan
Write-Host "Base Python: $BasePython"
Write-Host "Runtime: $VenvRoot"

New-Item -ItemType Directory -Force -Path (Split-Path $VenvRoot -Parent) | Out-Null
& $BasePython -m venv $VenvRoot
if ($LASTEXITCODE -ne 0) {
    throw "Could not create the bundle-local Python environment."
}

& $VenvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "pip upgrade failed."
}

& $VenvPython -m pip install -r $Requirements
if ($LASTEXITCODE -ne 0) {
    throw "Python dependency installation failed."
}

Test-BundleRuntime -PythonExe $VenvPython

Write-Host ""
Write-Host "[PASS] Bundle-local Python runtime is ready." -ForegroundColor Green
Write-Host "You can now run Start_NBA_Franchise_Simulator_V3.cmd."
