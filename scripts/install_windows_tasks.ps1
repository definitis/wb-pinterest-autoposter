param(
    [Parameter(Mandatory = $true)]
    [string]$SellerUrl,

    [string]$Python = "python",
    [string]$SocialTaskName = "WB Autoposter Social Cycle",
    [string]$MetricsTaskName = "WB Autoposter Metrics Sync",
    [string]$SocialTime = "10:00",
    [string]$MetricsTime = "22:00",
    [int]$ScanLimit = 100,
    [int]$PinterestLimit = 1,
    [int]$InstagramLimit = 1,
    [switch]$RealPublish,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$SocialScript = Join-Path $PSScriptRoot "run_social_cycle.ps1"
$MetricsScript = Join-Path $PSScriptRoot "sync_metrics.ps1"

$SocialCommand = @(
    "powershell.exe",
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", "`"$SocialScript`"",
    "-SellerUrl", "`"$SellerUrl`"",
    "-Python", "`"$Python`"",
    "-ScanLimit", "$ScanLimit",
    "-PinterestLimit", "$PinterestLimit",
    "-InstagramLimit", "$InstagramLimit"
)

if ($RealPublish) {
    $SocialCommand += "-RealPublish"
}

$MetricsCommand = @(
    "powershell.exe",
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", "`"$MetricsScript`"",
    "-Python", "`"$Python`"",
    "-Platform", "all"
)

$CreateArgs = @("/Create", "/SC", "DAILY")
if ($Force) {
    $CreateArgs += "/F"
}

schtasks.exe @CreateArgs /TN $SocialTaskName /ST $SocialTime /TR ($SocialCommand -join " ")
schtasks.exe @CreateArgs /TN $MetricsTaskName /ST $MetricsTime /TR ($MetricsCommand -join " ")

Write-Host "Created scheduled tasks:"
Write-Host " - $SocialTaskName at $SocialTime"
Write-Host " - $MetricsTaskName at $MetricsTime"
