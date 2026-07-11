param(
    [string]$ProjectRoot = "G:\OwnProject\daily_stock_analysis",
    [string]$BindAddress = "127.0.0.1",
    [int]$Port = 8000,
    [int]$WaitSeconds = 90
)

$ErrorActionPreference = "Stop"
$python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$main = Join-Path $ProjectRoot "main.py"
$logs = Join-Path $ProjectRoot "logs"
$healthUrl = "http://${BindAddress}:${Port}/api/health"

if (-not (Test-Path $python)) {
    throw "DSA virtual environment is missing: $python"
}
if (-not (Test-Path $main)) {
    throw "DSA entry point is missing: $main"
}

foreach ($directory in @("data", "logs", "reports", "longbridge_tokens")) {
    New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot $directory) | Out-Null
}

try {
    $response = Invoke-WebRequest -UseBasicParsing -Uri $healthUrl -TimeoutSec 3
    if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) {
        Write-Output "DSA server is already healthy: $healthUrl"
        exit 0
    }
} catch {
    # The service is not running yet.
}

$existing = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -and $_.CommandLine.Contains($main) -and $_.CommandLine.Contains("--serve-only")
}
if (-not $existing) {
    $stamp = Get-Date -Format "yyyyMMdd"
    $stdout = Join-Path $logs "server_${stamp}.out.log"
    $stderr = Join-Path $logs "server_${stamp}.err.log"
    Start-Process `
        -FilePath $python `
        -ArgumentList @($main, "--serve-only", "--host", $BindAddress, "--port", $Port) `
        -WorkingDirectory $ProjectRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr
}

$deadline = (Get-Date).AddSeconds($WaitSeconds)
do {
    Start-Sleep -Seconds 2
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $healthUrl -TimeoutSec 3
        if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) {
            Write-Output "DSA server is healthy: $healthUrl"
            exit 0
        }
    } catch {
        # Keep waiting until the deadline.
    }
} while ((Get-Date) -lt $deadline)

throw "DSA server did not become healthy in $WaitSeconds seconds. Check $logs."
