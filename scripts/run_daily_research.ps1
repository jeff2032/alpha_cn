param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$UniverseFile = "data/universe/a_stock.csv",
    [string]$Since = "2020-01-01",
    [double]$SleepSeconds = 1.0,
    [string]$ProbeSymbol = "000001",
    [switch]$Force
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
        throw "命令失败，退出码: $LASTEXITCODE"
    }
}

function Get-CacheLastDate {
    param([string]$Symbol)
    $path = Join-Path $ProjectRoot "data/cache/akshare/daily/$Symbol.csv"
    if (-not (Test-Path $path)) {
        return $null
    }
    $lastLine = Get-Content -LiteralPath $path -Tail 1
    if (-not $lastLine) {
        return $null
    }
    $dateText = ($lastLine -split ",")[0]
    try {
        return ([datetime]$dateText).ToString("yyyy-MM-dd")
    } catch {
        return $null
    }
}

function Get-LatestCacheDate {
    $cacheDir = Join-Path $ProjectRoot "data/cache/akshare/daily"
    if (-not (Test-Path $cacheDir)) {
        return $null
    }

    $latest = $null
    Get-ChildItem -LiteralPath $cacheDir -Filter "*.csv" | ForEach-Object {
        $lastLine = Get-Content -LiteralPath $_.FullName -Tail 1
        if ($lastLine) {
            $dateText = ($lastLine -split ",")[0]
            try {
                $date = [datetime]$dateText
                if ($null -eq $latest -or $date -gt $latest) {
                    $latest = $date
                }
            } catch {
            }
        }
    }

    if ($null -eq $latest) {
        return $null
    }
    return $latest.ToString("yyyy-MM-dd")
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

$logDir = Join-Path $ProjectRoot "logs/daily_research"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logPath = Join-Path $logDir ("daily_research_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
Start-Transcript -Path $logPath -Append | Out-Null

try {
    Write-Step "每日研究任务开始，项目目录: $ProjectRoot"

    $today = Get-Date
    if (-not $Force -and ($today.DayOfWeek -eq "Saturday" -or $today.DayOfWeek -eq "Sunday")) {
        Write-Step "今天是周末，跳过。"
        return
    }

    $venvPython = Join-Path $ProjectRoot ".venv/Scripts/python.exe"
    if (Test-Path $venvPython) {
        $script:PythonExe = $venvPython
    } else {
        $script:PythonExe = "python"
    }
    $env:PYTHONPATH = (Join-Path $ProjectRoot "src") + [IO.Path]::PathSeparator + $env:PYTHONPATH

    $universePath = Join-Path $ProjectRoot $UniverseFile
    if (-not (Test-Path $universePath)) {
        throw "股票池不存在: $universePath"
    }

    $targetDate = $today.ToString("yyyy-MM-dd")
    $probeBefore = Get-CacheLastDate -Symbol $ProbeSymbol
    Write-Step "探针标的 $ProbeSymbol 更新前最后日期: $probeBefore"
    Invoke-Quant @(
        "sync-daily",
        "--symbols", $ProbeSymbol,
        "--since", $Since,
        "--adjust", "qfq",
        "--asset-type", "stock",
        "--stock-provider", "sina"
    )
    $probeAfter = Get-CacheLastDate -Symbol $ProbeSymbol
    Write-Step "探针标的 $ProbeSymbol 更新后最后日期: $probeAfter"

    if (-not $Force -and $probeAfter -lt $targetDate) {
        Write-Step "数据源尚未更新到 $targetDate，跳过全市场同步和研究报告。"
        return
    }

    $stalePath = Join-Path $ProjectRoot "data/universe/stale.csv"
    Invoke-Quant @(
        "cache-date-status",
        "--universe-file", $UniverseFile,
        "--target-date", $targetDate,
        "--show-stale",
        "--top", "30",
        "--output-stale", "data/universe/stale.csv"
    )

    $staleCount = Get-CsvDataRowCount -Path $stalePath
    Write-Step "过期标的数量: $staleCount"
    if ($staleCount -gt 0) {
        Invoke-Quant @(
            "sync-stock-universe",
            "--universe-file", "data/universe/stale.csv",
            "--since", $Since,
            "--stock-provider", "sina",
            "--adjust", "qfq",
            "--sleep", $SleepSeconds.ToString([Globalization.CultureInfo]::InvariantCulture),
            "--no-skip-existing"
        )
    }

    $latestCacheDate = Get-LatestCacheDate
    if (-not $latestCacheDate) {
        throw "无法从缓存推断最新交易日。"
    }
    Write-Step "报告使用最新缓存交易日: $latestCacheDate"

    Invoke-Quant @(
        "scan-pattern",
        "--pattern", "base_breakout_setup",
        "--top", "120",
        "--min-score", "50",
        "--stages", "watch", "near_breakout",
        "--min-amount-ma20", "100000000",
        "--require-positive-trend-slope",
        "--max-close-vs-trend", "0.25",
        "--filter-max-ret-20", "0.25"
    )
    Invoke-Quant @(
        "scan-pattern",
        "--pattern", "accumulation_setup",
        "--top", "120",
        "--min-score", "50",
        "--stages", "accumulation",
        "--base-window", "250",
        "--max-base-range", "0.45",
        "--min-amount-ma20", "100000000",
        "--min-volume-ratio", "1.05",
        "--max-volume-ratio", "2.20",
        "--require-positive-trend-slope",
        "--max-close-vs-trend", "0.12",
        "--max-close-vs-cost", "0.18",
        "--filter-max-ret-20", "0.15",
        "--max-ret-60", "0.30",
        "--max-price-position", "0.82"
    )
    Invoke-Quant @(
        "sentiment-score",
        "--latest-scan",
        "--target-date", $latestCacheDate,
        "--top", "50",
        "--display-top", "30",
        "--news-days", "7",
        "--research-days", "90"
    )
    Invoke-Quant @(
        "market-theme",
        "--target-date", $latestCacheDate,
        "--top", "20"
    )
    Invoke-Quant @(
        "research-candidates",
        "--target-date", $latestCacheDate,
        "--top", "30"
    )
    Invoke-Quant @(
        "snapshot-research",
        "--target-date", $latestCacheDate
    )
    Invoke-Quant @(
        "daily-research-summary",
        "--target-date", $latestCacheDate,
        "--top", "30"
    )

    Write-Step "每日研究任务完成。日志: $logPath"
} catch {
    Write-Step ("每日研究任务失败: " + $_.Exception.Message)
    throw
} finally {
    Stop-Transcript | Out-Null
}
