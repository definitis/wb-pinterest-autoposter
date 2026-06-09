param(
    [string]$Python = "python",
    [ValidateSet("all", "pinterest", "instagram")]
    [string]$Platform = "all",
    [int]$Limit = 50,
    [int]$ReportLimit = 20
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

& $Python -m wb_autoposter.cli sync-metrics --platform $Platform --limit $Limit
& $Python -m wb_autoposter.cli metrics-report --platform $Platform --limit $ReportLimit
