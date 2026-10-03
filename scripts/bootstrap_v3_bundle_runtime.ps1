param()

$ErrorActionPreference = "Stop"

$AppRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BundleRoot = (Resolve-Path (Join-Path $AppRoot "..")).Path
$VenvRoot = Join-Path $BundleRoot "runtime\venv"
$VenvPython = Join-Path $VenvRoot "Scripts\python.exe"
$Requirements = Join-Path $AppRoot "requirements.txt"

function Resolve-BasePython {
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

    throw "Python was not found. Install 64-bit Python 3.12, then run Setup_Runtime.cmd again."
}

if (-not (Test-Path $Requirements -PathType Leaf)) {
    throw "requirements.txt is missing from the application bundle."
}

if (Test-Path $VenvPython -PathType Leaf) {
    Write-Host "[OK] Bundle-local Python runtime already exists: $VenvPython" -ForegroundColor Green
    & $VenvPython -c "import starlette, uvicorn, cloudpickle; print('Core V3 runtime imports: PASS')"
    exit $LASTEXITCODE
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

& $VenvPython -c "import starlette, uvicorn, cloudpickle; print('Core V3 runtime imports: PASS')"
if ($LASTEXITCODE -ne 0) {
    throw "Runtime import verification failed."
}

Write-Host ""
Write-Host "[PASS] Bundle-local Python runtime is ready." -ForegroundColor Green
Write-Host "You can now run Start_NBA_Franchise_Simulator_V3.cmd."
