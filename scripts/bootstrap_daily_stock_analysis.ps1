param(
    [string]$ProjectRoot = "G:\OwnProject\daily_stock_analysis",
    [string]$AlphaRoot = "G:\OwnProject\alpha_cn"
)

$ErrorActionPreference = "Stop"
$python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$constraints = Join-Path $AlphaRoot "config\dsa-windows-constraints.txt"

if (-not (Test-Path (Join-Path $ProjectRoot "requirements.txt"))) {
    throw "Invalid DSA project root: $ProjectRoot"
}
if (-not (Test-Path $constraints)) {
    throw "Missing Windows constraints: $constraints"
}

if (-not (Test-Path $python)) {
    python -m venv (Join-Path $ProjectRoot ".venv")
}

& $python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "Failed to upgrade pip." }
& $python -m pip install -r (Join-Path $ProjectRoot "requirements.txt") -c $constraints --prefer-binary
if ($LASTEXITCODE -ne 0) { throw "Failed to install DSA Python dependencies." }
& $python -m pip check
if ($LASTEXITCODE -ne 0) { throw "DSA dependency check failed." }

$webRoot = Join-Path $ProjectRoot "apps\dsa-web"
Push-Location $webRoot
try {
    npm ci --prefer-offline --no-audit
    if ($LASTEXITCODE -ne 0) { throw "Failed to install DSA Web dependencies." }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "Failed to build DSA Web." }
} finally {
    Pop-Location
}

foreach ($directory in @("data", "logs", "reports", "longbridge_tokens")) {
    New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot $directory) | Out-Null
}

Write-Output "DSA bootstrap completed: $ProjectRoot"
