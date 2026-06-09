param(
    [Parameter(Mandatory = $true)]
    [string]$SellerUrl,

    [string]$Python = "python",
    [int]$ScanLimit = 100,
    [int]$PinterestLimit = 1,
    [int]$InstagramLimit = 1,
    [int]$VkLimit = 1,
    [switch]$IncludeVk,
    [switch]$NoPinterest,
    [switch]$NoInstagram,
    [switch]$RealPublish
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$CycleArgs = @(
    "-m", "wb_autoposter.cli",
    "wb-social-cycle",
    "--seller-url", $SellerUrl,
    "--scan-limit", "$ScanLimit",
    "--pinterest-limit", "$PinterestLimit",
    "--instagram-limit", "$InstagramLimit",
    "--vk-limit", "$VkLimit",
    "--pinterest-zernio",
    "--headless",
    "--no-manual-ready"
)

if ($RealPublish) {
    $CycleArgs += "--no-dry-run"
} else {
    $CycleArgs += "--dry-run"
}

if ($IncludeVk) {
    $CycleArgs += "--vk"
} else {
    $CycleArgs += "--no-vk"
}

if ($NoPinterest) {
    $CycleArgs += "--no-pinterest"
} else {
    $CycleArgs += "--pinterest"
}

if ($NoInstagram) {
    $CycleArgs += "--no-instagram"
} else {
    $CycleArgs += "--instagram"
}

& $Python @CycleArgs
