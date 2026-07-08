param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$UniverseFile = "data/universe/a_stock.csv",
    [string]$Since = "2020-01-01",
    [string]$TargetDate = "",
    [string]$StockProvider = "sina",
    [string]$FallbackStockProvider = "eastmoney",
    [string]$Adjust = "qfq",
    [int]$Workers = 6,
    [int]$FallbackWorkers = 6,
    [double]$SleepSeconds = 0.05,
    [int]$LookbackDays = 60,
    [switch]$SkipUniverseRefresh,
    [switch]$NoFallback
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    $now = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Write-Host "[$now] $Message"
}

function Invoke-Quant {
    param(
        [string[]]$Arguments,
        [switch]$AllowFailure
    )

    $script:LastQuantSucceeded = $true
    Write-Step ("python -m quant_a_stock.cli " + ($Arguments -join " "))
    & $script:PythonExe -m quant_a_stock.cli @Arguments
    if ($LASTEXITCODE -ne 0) {
        $script:LastQuantSucceeded = $false
        $message = "Command failed, exit code: $LASTEXITCODE"
        if ($AllowFailure) {
            Write-Step "$message; continue and refresh stale list."
            return
        }
        throw $message
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

function Get-EffectiveWorkers {
    param(
        [string]$Provider,
        [int]$RequestedWorkers
    )

    $effective = [Math]::Max(1, $RequestedWorkers)
    if ($Provider -eq "sina" -and $effective -gt 1) {
        Write-Step "Sina provider is not stable with high thread counts on this machine; clamp Workers from $effective to 1."
        return 1
    }
    if ($Provider -eq "eastmoney" -and $effective -gt 2) {
        Write-Step "Eastmoney provider is unstable with large full-market bursts; clamp Workers from $effective to 2."
        return 2
    }
    return $effective
}

function Invoke-CacheDateStatus {
    param(
        [string]$OutputStale,
        [string]$Top = "30"
    )

    $statusArgs = @(
        "cache-date-status",
        "--universe-file", $UniverseFile,
        "--show-stale",
        "--top", $Top,
        "--output-stale", $OutputStale
    )
    if ($TargetDate) {
        $statusArgs += @("--target-date", $TargetDate)
        $statusArgs += @("--exact-target-date")
    }
    Invoke-Quant $statusArgs
}

function Invoke-UniverseSync {
    param(
        [string]$Name,
        [string]$Provider,
        [int]$RequestedWorkers,
        [switch]$AllowFailure
    )

    if ($Provider -notin @("sina", "eastmoney")) {
        throw "Unsupported stock provider: $Provider"
    }

    $effectiveWorkers = Get-EffectiveWorkers -Provider $Provider -RequestedWorkers $RequestedWorkers
    $effectiveSleep = [Math]::Max($SleepSeconds, 0.2)
    Write-Step "$Name. Provider: $Provider, Workers: $effectiveWorkers, SleepSeconds: $effectiveSleep, LookbackDays: $LookbackDays"
    Invoke-Quant @(
        "sync-stock-universe",
        "--universe-file", "data/universe/stale.csv",
        "--since", $Since,
        "--stock-provider", $Provider,
        "--adjust", $Adjust,
        "--incremental",
        "--lookback-days", $LookbackDays.ToString([Globalization.CultureInfo]::InvariantCulture),
        "--workers", $effectiveWorkers.ToString([Globalization.CultureInfo]::InvariantCulture),
        "--sleep", $effectiveSleep.ToString([Globalization.CultureInfo]::InvariantCulture),
        "--retries", "3",
        "--retry-wait", "2",
        "--max-consecutive-failures", "40",
        "--no-skip-existing"
    ) -AllowFailure:$AllowFailure
    $script:LastSyncSucceeded = $script:LastQuantSucceeded
}

Set-Location $ProjectRoot

$logDir = Join-Path $ProjectRoot "logs/data_sync"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logPath = Join-Path $logDir ("data_sync_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
Start-Transcript -Path $logPath -Append | Out-Null

try {
    Write-Step "Data sync started. ProjectRoot: $ProjectRoot"
    Write-Step "Primary provider: $StockProvider, fallback provider: $FallbackStockProvider, SleepSeconds: $SleepSeconds, LookbackDays: $LookbackDays"

    $venvPython = Join-Path $ProjectRoot ".venv/Scripts/python.exe"
    if (Test-Path $venvPython) {
        $script:PythonExe = $venvPython
    } else {
        $script:PythonExe = "python"
    }
    $env:PYTHONPATH = (Join-Path $ProjectRoot "src") + [IO.Path]::PathSeparator + $env:PYTHONPATH

    if (-not $SkipUniverseRefresh) {
        Invoke-Quant @(
            "refresh-stock-universe",
            "--existing-file", $UniverseFile,
            "--output", $UniverseFile,
            "--manual-files", "config/required_symbols.csv"
        ) -AllowFailure
        if (-not $script:LastQuantSucceeded) {
            Write-Step "Universe refresh failed. Keep existing universe file and continue data sync."
        }
    } else {
        Write-Step "Universe refresh skipped by parameter."
    }

    $stalePath = Join-Path $ProjectRoot "data/universe/stale.csv"
    Invoke-CacheDateStatus -OutputStale "data/universe/stale.csv" -Top "30"

    $staleCount = Get-CsvDataRowCount -Path $stalePath
    Write-Step "Stale symbols: $staleCount"
    if ($staleCount -le 0) {
        Write-Step "No stale symbols. Data sync finished."
        return
    }

    Invoke-UniverseSync -Name "Primary daily sync" -Provider $StockProvider -RequestedWorkers $Workers -AllowFailure
    if (-not $script:LastSyncSucceeded) {
        Write-Step "Primary provider failed or crashed. Refresh stale list before fallback."
    }
    Invoke-CacheDateStatus -OutputStale "data/universe/stale.csv" -Top "30"

    $staleCount = Get-CsvDataRowCount -Path $stalePath
    Write-Step "Stale symbols after primary provider: $staleCount"
    if ($staleCount -gt 0 -and -not $NoFallback -and $FallbackStockProvider -and $FallbackStockProvider -ne $StockProvider) {
        Invoke-UniverseSync -Name "Fallback daily sync" -Provider $FallbackStockProvider -RequestedWorkers $FallbackWorkers -AllowFailure
        if (-not $script:LastSyncSucceeded) {
            Write-Step "Fallback provider failed or crashed. Continue to final coverage check."
        }
    } elseif ($staleCount -gt 0 -and ($NoFallback -or -not $FallbackStockProvider)) {
        Write-Step "Fallback provider disabled. Continue to final coverage check."
    }

    Invoke-CacheDateStatus -OutputStale "data/universe/stale.csv" -Top "20"
    $finalStaleCount = Get-CsvDataRowCount -Path $stalePath
    if ($finalStaleCount -gt 0) {
        Write-Step "Data sync finished with stale symbols remaining: $finalStaleCount. Nightly prep will decide whether to retry or continue."
    }
    Write-Step "Data sync finished. Log: $logPath"
} finally {
    Stop-Transcript | Out-Null
}
