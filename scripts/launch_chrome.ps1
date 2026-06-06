# Launch a dedicated "job applications" Chrome with remote debugging so the tool
# can attach over CDP.
#
# Chrome 136+ refuses to open the debug port on your default profile (security
# change), so we use a separate --user-data-dir. This runs as its own instance,
# so you don't need to quit your normal Chrome.
#
# Usage: .\scripts\launch_chrome.ps1 [-Port 9222]

param(
    [int]$Port = 9222
)

$chromePaths = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
)

$chrome = $chromePaths | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $chrome) {
    Write-Error "Chrome not found. Checked:`n  $($chromePaths -join "`n  ")"
    exit 1
}

$dataDir = Join-Path $env:LOCALAPPDATA "workday-autofill-chrome"
if (-not (Test-Path $dataDir)) {
    New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
}

Write-Host "Launching dedicated applications Chrome (CDP port $Port)..."
Write-Host "Profile dir: $dataDir"
Write-Host "(Your normal Chrome can stay open - this is a separate instance.)"

& $chrome `
    --remote-debugging-port=$Port `
    --user-data-dir="$dataDir" `
    --no-first-run `
    --no-default-browser-check
