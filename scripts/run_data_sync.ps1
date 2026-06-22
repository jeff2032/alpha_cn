param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$UniverseFile = "data/universe/a_stock.csv",
    [string]$Since = "2020-01-01",
    [string]$TargetDate = "",
    [string]$StockProvider = "sina",
    [string]$Adjust = "qfq",
    [int]$Workers = 6,
    [double]$SleepSeconds = 0.05,
    [int]$LookbackDays = 60
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    $now = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Write-Host "[$now] $Message"
}

function Invoke-Quant {
    param([string[]]$Arguments)
    Write-Step ("python -m quant_a_stock.cli " + ($Arguments -join " "))
    & $script:PythonExe -m quant_a_stock.cli @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed, exit code: $LASTEXITCODE"
    }
}

function Get-CsvDataRowCount {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        return 0
    }
    $lineCount = (Get-Content -LiteralPath $Path | Measure-Object -Line).Lines
    return [Math]::Max(0, $lineCount - 1)
}

Set-Location $ProjectRoot

$logDir = Join-Path $ProjectRoot "logs/data_sync"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logPath = Join-Path $logDir ("data_sync_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
Start-Transcript -Path $logPath -Append | Out-Null

try {
    Write-Step "Data sync started. ProjectRoot: $ProjectRoot"
    $effectiveWorkers = $Workers
    if ($StockProvider -eq "sina" -and $Workers -gt 2) {
        $effectiveWorkers = 2
        Write-Step "Sina provider is not stable with high thread counts on this machine; clamp Workers from $Workers to $effectiveWorkers."
    }
    Write-Step "Provider: $StockProvider, Workers: $effectiveWorkers, SleepSeconds: $SleepSeconds, LookbackDays: $LookbackDays"

    $venvPython = Join-Path $ProjectRoot ".venv/Scripts/python.exe"
    if (Test-Path $venvPython) {
        $script:PythonExe = $venvPython
    } else {
        $script:PythonExe = "python"
    }
    $env:PYTHONPATH = (Join-Path $ProjectRoot "src") + [IO.Path]::PathSeparator + $env:PYTHONPATH

    $stalePath = Join-Path $ProjectRoot "data/universe/stale.csv"
    $statusArgs = @(
        "cache-date-status",
        "--universe-file", $UniverseFile,
        "--show-stale",
        "--top", "30",
        "--output-stale", "data/universe/stale.csv"
    )
    if ($TargetDate) {
        $statusArgs += @("--target-date", $TargetDate)
        $statusArgs += @("--exact-target-date")
    }
    Invoke-Quant $statusArgs

    $staleCount = Get-CsvDataRowCount -Path $stalePath
    Write-Step "Stale symbols: $staleCount"
    if ($staleCount -le 0) {
        Write-Step "No stale symbols. Data sync finished."
        return
    }

    Invoke-Quant @(
        "sync-stock-universe",
        "--universe-file", "data/universe/stale.csv",
        "--since", $Since,
        "--stock-provider", $StockProvider,
        "--adjust", $Adjust,
        "--incremental",
        "--lookback-days", $LookbackDays.ToString([Globalization.CultureInfo]::InvariantCulture),
        "--workers", $effectiveWorkers.ToString([Globalization.CultureInfo]::InvariantCulture),
        "--sleep", $SleepSeconds.ToString([Globalization.CultureInfo]::InvariantCulture),
        "--no-skip-existing"
    )

    $finalStatusArgs = @(
        "cache-date-status",
        "--universe-file", $UniverseFile,
        "--show-stale",
        "--top", "20"
    )
    if ($TargetDate) {
        $finalStatusArgs += @("--target-date", $TargetDate)
        $finalStatusArgs += @("--exact-target-date")
    }
    Invoke-Quant $finalStatusArgs
    Write-Step "Data sync finished. Log: $logPath"
} finally {
    Stop-Transcript | Out-Null
}
