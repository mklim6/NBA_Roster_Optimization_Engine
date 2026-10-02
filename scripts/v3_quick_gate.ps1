param(
    [string]$GodotPath = "C:\Users\klima\Downloads\Godot_v4.0-stable_win64.exe\Godot_v4.0-stable_win64.exe",
    [switch]$RequireBridge
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$expectedV2 = "6b9cb89d78a9c143a62c9460375b96cdf215dfbf9ac713001755ac7045c8718d"
$v2Path = ".\outputs\runtime\franchise_mode_checkpoint_v1.pkl.gz"
$failed = $false

function Pass([string]$message) {
    Write-Host "[PASS] $message" -ForegroundColor Green
}

function Warn([string]$message) {
    Write-Host "[WARN] $message" -ForegroundColor Yellow
}

function Fail([string]$message) {
    Write-Host "[FAIL] $message" -ForegroundColor Red
    $script:failed = $true
}

Write-Host ""
Write-Host "=== V3 QUICK GATE ===" -ForegroundColor Cyan

# Godot parser/runtime smoke.
if (Test-Path $GodotPath) {
    & $GodotPath --headless --path ".\godot_client" --quit-after 3
    if ($LASTEXITCODE -eq 0) {
        Pass "Godot headless smoke"
    } else {
        Fail "Godot headless smoke exit code $LASTEXITCODE"
    }
} else {
    Fail "Godot executable not found: $GodotPath"
}

# Python bridge syntax.
python -m py_compile ".\desktop_bridge\server.py"
if ($LASTEXITCODE -eq 0) {
    Pass "desktop_bridge/server.py compiles"
} else {
    Fail "desktop_bridge/server.py compilation"
}

# Git whitespace check.
git diff --check
if ($LASTEXITCODE -eq 0) {
    Pass "git diff --check"
} else {
    Fail "git diff --check"
}

# Protected V2 hash.
if (Test-Path $v2Path) {
    $actualV2 = (Get-FileHash $v2Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualV2 -eq $expectedV2) {
        Pass "Protected V2 checkpoint hash unchanged"
    } else {
        Fail "Protected V2 checkpoint hash CHANGED: $actualV2"
    }
} else {
    Fail "Protected V2 checkpoint not found"
}

# Bridge / working-save safety when the server is live.
$bridgeLive = $false
try {
    $health = Invoke-RestMethod "http://127.0.0.1:8765/health" -TimeoutSec 2
    $bridgeLive = $true
    Pass "Bridge health API $($health.api_version)"

    $save = Invoke-RestMethod "http://127.0.0.1:8765/v3/working-save/status" -TimeoutSec 3
    if ($save.active_v2_read_only -eq $true -and $save.active_v2_sha256 -eq $expectedV2) {
        Pass "Bridge reports V2 read-only and hash protected"
    } else {
        Fail "Bridge V2 safety status is not valid"
    }

    if ($save.working_save_exists -eq $true) {
        Pass "V3 working save exists"
    } else {
        Fail "V3 working save is missing"
    }
} catch {
    if ($RequireBridge) {
        Fail "Bridge is not reachable on port 8765"
    } else {
        Warn "Bridge offline; live endpoint checks skipped"
    }
}

Write-Host ""
Write-Host "Changed files:" -ForegroundColor Cyan
git status --short

Write-Host ""
if ($failed) {
    Write-Host "V3 QUICK GATE: FAILED" -ForegroundColor Red
    exit 1
}

Write-Host "V3 QUICK GATE: PASSED" -ForegroundColor Green
exit 0
