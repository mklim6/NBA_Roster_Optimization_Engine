param(
    [string]$GodotPath = "C:\Users\klima\Downloads\Godot_v4.0-stable_win64.exe",
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

# Godot parser/editor smoke.
# Godot 4.0 writes benign editor warnings to stderr and may return exit code 1.
# Capture stdout/stderr to files so PowerShell does not turn stderr into a terminating NativeCommandError.
if (Test-Path $GodotPath) {
    $godotStdout = Join-Path $env:TEMP "v3_godot_gate_stdout.txt"
    $godotStderr = Join-Path $env:TEMP "v3_godot_gate_stderr.txt"

    Remove-Item $godotStdout, $godotStderr -Force -ErrorAction SilentlyContinue

    $godotProcess = Start-Process `
        -FilePath $GodotPath `
        -ArgumentList @("--headless", "--editor", "--path", ".\godot_client", "--quit") `
        -RedirectStandardOutput $godotStdout `
        -RedirectStandardError $godotStderr `
        -NoNewWindow `
        -Wait `
        -PassThru

    $godotExit = $godotProcess.ExitCode
    $godotOutput = ""

    if (Test-Path $godotStdout) {
        $godotOutput += (Get-Content $godotStdout -Raw -ErrorAction SilentlyContinue)
    }
    if (Test-Path $godotStderr) {
        $godotOutput += "`n" + (Get-Content $godotStderr -Raw -ErrorAction SilentlyContinue)
    }

    $fatalGodotPatterns = @(
        "Parse Error",
        "SCRIPT ERROR",
        "Failed to load script",
        "Error loading script",
        "Cannot load source code",
        "Parser Error"
    )

    $fatalGodotError = $false
    foreach ($pattern in $fatalGodotPatterns) {
        if ($godotOutput -match [regex]::Escape($pattern)) {
            $fatalGodotError = $true
            break
        }
    }

    if ($fatalGodotError) {
        Fail "Godot parser/editor smoke found a script error"
        Write-Host $godotOutput
    } else {
        Pass "Godot parser/editor smoke"
        if ($godotExit -ne 0) {
            Warn "Godot editor returned exit code $godotExit with no script/parser error; benign Godot 4.0 headless warnings were ignored."
        }
    }

    Remove-Item $godotStdout, $godotStderr -Force -ErrorAction SilentlyContinue
} else {
    Fail "Godot executable not found: $GodotPath"
}

# Python bridge syntax.
python -m py_compile ".\desktop_bridge\server.py" ".\desktop_bridge\transaction_foundation.py" ".\desktop_bridge\runtime_performance_foundation.py"
if ($LASTEXITCODE -eq 0) {
    Pass "desktop_bridge server + transaction + runtime performance foundations compile"
} else {
    Fail "desktop_bridge Python compilation"
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

    $serverText = Get-Content ".\desktop_bridge\server.py" -Raw
    $versionMatch = [regex]::Match($serverText, 'API_VERSION\s*=\s*"([^"]+)"')
    $sourceApiVersion = if ($versionMatch.Success) { $versionMatch.Groups[1].Value } else { $null }

    if ($sourceApiVersion -and $health.api_version -eq $sourceApiVersion) {
        Pass "Bridge API matches source: $sourceApiVersion"
    } elseif ($sourceApiVersion) {
        Fail "Running bridge API $($health.api_version) does not match source API $sourceApiVersion. Restart the bridge."
    } else {
        Fail "Could not determine API_VERSION from desktop_bridge/server.py"
    }

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

    if ($serverText -match '/v3/runtime/performance') {
        try {
            $runtime = Invoke-RestMethod "http://127.0.0.1:8765/v3/runtime/performance" -TimeoutSec 5
            if ($runtime.runtime_version -and $null -ne $runtime.cache.hit_rate) {
                Pass "Runtime performance telemetry + read cache endpoint"
            } else {
                Fail "Runtime performance endpoint returned an incomplete payload"
            }
        } catch {
            Fail "Runtime performance endpoint failed: $($_.Exception.Message)"
        }
    }

    if ($serverText -match '/v3/market-intelligence') {
        try {
            $market = Invoke-RestMethod "http://127.0.0.1:8765/v3/market-intelligence" -TimeoutSec 30
            if ($market.team -and $null -ne $market.free_agency.total_available) {
                Pass "Market intelligence endpoint ($($market.free_agency.total_available) free agents)"
            } else {
                Fail "Market intelligence endpoint returned an incomplete payload"
            }
        } catch {
            Fail "Market intelligence endpoint failed: $($_.Exception.Message)"
        }
    }

    if ($serverText -match '/v3/free-agency/market') {
        try {
            $faMarket = Invoke-RestMethod "http://127.0.0.1:8765/v3/free-agency/market" -TimeoutSec 30
            if (
                $faMarket.total_available -gt 0 -and
                $faMarket.working_save_unchanged -eq $true -and
                $faMarket.active_v2_unchanged -eq $true
            ) {
                Pass "Full free-agency market endpoint ($($faMarket.total_available) players, read-only)"
            } else {
                Fail "Full free-agency market endpoint failed safety/payload checks"
            }
        } catch {
            Fail "Full free-agency market endpoint failed: $($_.Exception.Message)"
        }
    }

    if ($serverText -match '/v3/trade/team-assets') {
        try {
            $foundation = Invoke-RestMethod "http://127.0.0.1:8765/v3/transaction-foundation?trade_finder=0" -TimeoutSec 30
            if (
                $foundation.team -and
                $foundation.working_save_unchanged -eq $true -and
                $foundation.active_v2_unchanged -eq $true
            ) {
                $teamCode = $foundation.team
                $teamAssets = Invoke-RestMethod "http://127.0.0.1:8765/v3/trade/team-assets?team=$teamCode" -TimeoutSec 30
                if (
                    $teamAssets.team -eq $teamCode -and
                    $teamAssets.working_save_unchanged -eq $true -and
                    $teamAssets.active_v2_unchanged -eq $true
                ) {
                    Pass "Trade team-assets endpoint ($teamCode, $($teamAssets.player_count) players, read-only)"
                } else {
                    Fail "Trade team-assets endpoint failed safety/payload checks"
                }
            } else {
                Fail "Transaction foundation read-only safety check failed"
            }
        } catch {
            Fail "Batch 07 transaction endpoint check failed: $($_.Exception.Message)"
        }
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
