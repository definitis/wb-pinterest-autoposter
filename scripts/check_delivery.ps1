param(
    [string]$Python = "python",
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$CheckRoot = Join-Path $ProjectRoot "out\delivery_check"
$CheckDb = Join-Path $CheckRoot "app.sqlite3"
$CheckOut = Join-Path $CheckRoot "artifacts"
$DashboardPath = Join-Path $CheckRoot "dashboard.html"
$FixturePath = Join-Path $ProjectRoot "data\fake_wb_products.json"
$CommandCwd = Join-Path ([System.IO.Path]::GetTempPath()) "wb_autoposter_delivery_check_cwd"
$SourcePath = Join-Path $ProjectRoot "src"

function Invoke-Check {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command
    )

    Write-Host ""
    Write-Host "==> $Name" -ForegroundColor Cyan
    Push-Location $CommandCwd
    try {
        & $Command
        if ($LASTEXITCODE -ne 0) {
            throw "Check failed: $Name"
        }
    } finally {
        Pop-Location
    }
}

function Write-WarningLine {
    param([string]$Message)
    Write-Host "WARN: $Message" -ForegroundColor Yellow
}

if (Test-Path $CheckRoot) {
    Remove-Item -LiteralPath $CheckRoot -Recurse -Force
}
if (Test-Path $CommandCwd) {
    Remove-Item -LiteralPath $CommandCwd -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $CheckRoot | Out-Null
New-Item -ItemType Directory -Force -Path $CommandCwd | Out-Null

# The delivery smoke-test must be safe and repeatable. It uses deterministic fallback
# text generation and never calls real social publishing APIs.
$env:GEMINI_API_KEY = ""
$env:ZERNIO_ENABLE_REAL_PUBLISH = "0"
$env:PINTEREST_ENABLE_REAL_PUBLISH = "0"
$env:INSTAGRAM_ENABLE_REAL_PUBLISH = "0"
$env:VK_ENABLE_REAL_PUBLISH = "0"
$env:VK_BROWSER_ENABLE = "0"
$env:WB_FAKE_PRODUCTS_PATH = $FixturePath
$env:PYTHONPATH = "$SourcePath$([System.IO.Path]::PathSeparator)$env:PYTHONPATH"

if (-not (Test-Path ".env")) {
    Write-WarningLine ".env not found. Copy .env.example to .env and fill real keys before real publishing."
}

if (-not (Test-Path $FixturePath)) {
    throw "Fixture not found: $FixturePath"
}

Invoke-Check "Python package imports" {
    & $Python -c "import wb_autoposter.cli; print('import ok')"
}

Invoke-Check "CLI configuration for test mode" {
    & $Python -m wb_autoposter.cli check-config --mode test
}

Invoke-Check "Safe dry-run cycle on fixture data" {
    & $Python -m wb_autoposter.cli run-cycle `
        --mode test `
        --platform pinterest `
        --db-path $CheckDb `
        --fixture-path $FixturePath `
        --out-dir $CheckOut
}

Invoke-Check "Static dashboard export" {
    & $Python -m wb_autoposter.cli export-dashboard `
        --db-path $CheckDb `
        --output $DashboardPath
}

if (-not (Test-Path $DashboardPath)) {
    throw "Dashboard was not created: $DashboardPath"
}

if (-not $SkipTests) {
    Invoke-Check "Focused delivery tests" {
        & $Python -m pytest (Join-Path $ProjectRoot "tests\test_cli.py") -k "export_dashboard or check_config_test_mode" -q
    }
}

Write-Host ""
Write-Host "Delivery smoke-test passed." -ForegroundColor Green
Write-Host "Dashboard: $DashboardPath"
Write-Host "Dry-run artifacts: $CheckOut"
