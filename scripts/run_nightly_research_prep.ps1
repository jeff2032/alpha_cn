param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$UniverseFile = "data/universe/a_stock.csv",
    [string]$Since = "2020-01-01",
    [string]$TargetDate = "",
    [string]$StockProvider = "sina",
    [string]$ReportCutoffTime = "15:30",
    [double]$SleepSeconds = 0.05,
    [int]$Workers = 6,
    [int]$LookbackDays = 60,
    [string]$FallbackStockProvider = "eastmoney",
    [int]$FallbackStockWorkers = 6,
    [string[]]$IndexSymbols = @("510300", "510500", "159915"),
    [string]$EtfProvider = "eastmoney",
    [string]$FallbackEtfProvider = "sina",
    [int]$SentimentTop = 180,
    [int]$RiskDays = 180,
    [int]$MaxStaleAllowed = 30,
    [int]$MaxSyncAttempts = 6,
    [int]$RetryWaitMinutes = 30,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    $now = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Write-Host "[$now] $Message"
}

function Add-StepResult {
    param(
        [string]$Name,
        [string]$Status,
        [string]$Detail = ""
    )

    $script:StepResults += [pscustomobject]@{
        time = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        name = $Name
        status = $Status
        detail = $Detail
    }
}

function Invoke-QuantStep {
    param(
        [string]$Name,
        [string[]]$Arguments
    )

    Write-Step ("${Name}: python -m quant_a_stock.cli " + ($Arguments -join " "))
    try {
        & $script:PythonExe -m quant_a_stock.cli @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "Command failed, exit code: $LASTEXITCODE"
        }
        Add-StepResult -Name $Name -Status "成功"
    } catch {
        Add-StepResult -Name $Name -Status "失败" -Detail $_.Exception.Message
        throw
    }
}

function Invoke-ScriptStep {
    param(
        [string]$Name,
        [string[]]$Arguments
    )

    Write-Step ("${Name}: powershell.exe " + ($Arguments -join " "))
    try {
        & powershell.exe @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "Command failed, exit code: $LASTEXITCODE"
        }
        Add-StepResult -Name $Name -Status "成功"
    } catch {
        Add-StepResult -Name $Name -Status "失败" -Detail $_.Exception.Message
        throw
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

function Get-PreviousWeekday {
    param([datetime]$Date)

    $day = $Date.Date
    while ($day.DayOfWeek -eq "Saturday" -or $day.DayOfWeek -eq "Sunday") {
        $day = $day.AddDays(-1)
    }
    return $day
}

function Get-CacheDateCoverage {
    param(
        [string]$CacheDir,
        [datetime]$Date,
        [int]$MinCount = 100
    )

    $targetText = $Date.ToString("yyyy-MM-dd")
    $count = 0
    foreach ($file in Get-ChildItem -LiteralPath $CacheDir -Filter "*.csv") {
        try {
            $match = Select-String -LiteralPath $file.FullName -Pattern $targetText -SimpleMatch -List -ErrorAction Stop
            if ($null -ne $match) {
                $count += 1
                if ($count -ge $MinCount) {
                    break
                }
            }
        } catch {
        }
    }
    return $count
}

function Resolve-CachedTradingDate {
    param([datetime]$Date)

    $cacheDir = Join-Path $ProjectRoot "data/cache/akshare/daily"
    if (-not (Test-Path $cacheDir)) {
        return (Get-PreviousWeekday -Date $Date).ToString("yyyy-MM-dd")
    }

    $target = $Date.Date
    $exactCount = Get-CacheDateCoverage -CacheDir $cacheDir -Date $target
    if ($exactCount -ge 100) {
        return $target.ToString("yyyy-MM-dd")
    }

    $counts = @{}
    Get-ChildItem -LiteralPath $cacheDir -Filter "*.csv" | ForEach-Object {
        try {
            $lastLine = Get-Content -LiteralPath $_.FullName -Tail 1
            if ($lastLine) {
                $dateText = ($lastLine -split ",")[0]
                $date = ([datetime]$dateText).ToString("yyyy-MM-dd")
                if (-not $counts.ContainsKey($date)) {
                    $counts[$date] = 0
                }
                $counts[$date] += 1
            }
        } catch {
        }
    }

    $latest = $null
    foreach ($key in $counts.Keys) {
        $candidate = [datetime]$key
        if ($counts[$key] -ge 100 -and $candidate -le $target) {
            if ($null -eq $latest -or $candidate -gt $latest) {
                $latest = $candidate
            }
        }
    }
    if ($null -ne $latest) {
        return $latest.ToString("yyyy-MM-dd")
    }
    return (Get-PreviousWeekday -Date $Date).ToString("yyyy-MM-dd")
}

function Get-DefaultTargetDate {
    param([string]$CutoffTime)

    $now = Get-Date
    $day = $now.Date
    $cutoff = [TimeSpan]::Parse($CutoffTime)
    if ($now.TimeOfDay -lt $cutoff) {
        $day = $day.AddDays(-1)
    }
    return (Get-PreviousWeekday -Date $day).ToString("yyyy-MM-dd")
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

function Get-CacheLastDate {
    param([string]$Symbol)

    $path = Join-Path $ProjectRoot "data/cache/akshare/daily/$Symbol.csv"
    if (-not (Test-Path -LiteralPath $path)) {
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

function Get-IndexStaleSymbols {
    param(
        [string[]]$Symbols,
        [string]$TargetDate
    )

    $target = [datetime]$TargetDate
    $stale = New-Object System.Collections.Generic.List[string]
    foreach ($symbol in $Symbols) {
        $lastDate = Get-CacheLastDate -Symbol $symbol
        if (-not $lastDate -or ([datetime]$lastDate) -lt $target) {
            $stale.Add($symbol)
        }
    }
    return $stale.ToArray()
}

function Resolve-DefaultDataDate {
    param([string]$CutoffTime)

    $candidate = Get-DefaultTargetDate -CutoffTime $CutoffTime
    return $candidate
}

function Normalize-DateString {
    param([string]$Value)

    try {
        $normalized = ([datetime]$Value).ToString("yyyy-MM-dd")
        return $normalized
    } catch {
        throw "Invalid date: $Value. Expected format like 2026-06-17."
    }
}

function Get-LatestReport {
    param([string]$Pattern)

    $reportsDir = Join-Path $ProjectRoot "reports"
    $report = Get-ChildItem -LiteralPath $reportsDir -Filter $Pattern |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($null -eq $report) {
        return ""
    }
    return $report.FullName
}

function Save-PrepReport {
    param(
        [string]$Status,
        [string]$Detail = "",
        [switch]$CheckpointOnly
    )

    $opsDir = Join-Path $ProjectRoot "reports/ops"
    New-Item -ItemType Directory -Force -Path $opsDir | Out-Null
    $currentPath = Join-Path $opsDir "nightly_prep_current.md"
    $reportPath = if ($CheckpointOnly) {
        $currentPath
    } else {
        Join-Path $opsDir ("nightly_prep_{0}.md" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
    }

    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add("# 夜间数据准备报告")
    $lines.Add("")
    $lines.Add("- 状态：$Status")
    $lines.Add("- 目标日期：$script:ResolvedTargetDate")
    $lines.Add("- 生成时间：$(Get-Date -Format "yyyy-MM-dd HH:mm:ss")")
    $lines.Add("- 日志：$script:LogPath")
    if ($Detail) {
        $lines.Add("- 说明：$Detail")
    }
    $lines.Add("")
    $lines.Add("## 数据覆盖")
    $lines.Add("")
    $lines.Add("- 准备后过期标的数：$script:FinalStaleCount")
    $lines.Add("- ETF/指数过期标的数：$script:FinalIndexStaleCount")
    $lines.Add("- 过期清单：data/universe/stale_after_nightly.csv")
    $lines.Add("")
    $lines.Add("## 步骤结果")
    $lines.Add("")
    $lines.Add("| 时间 | 步骤 | 状态 | 说明 |")
    $lines.Add("| --- | --- | --- | --- |")
    foreach ($step in $script:StepResults) {
        $detailText = [string]$step.detail
        $detailText = $detailText.Replace("|", "/")
        $lines.Add("| $($step.time) | $($step.name) | $($step.status) | $detailText |")
    }
    $lines.Add("")
    $lines.Add("## 最新输出")
    $lines.Add("")
    $lines.Add("- 情绪观察：$(Get-LatestReport -Pattern "sentiment_watchlist_*.md")")
    $lines.Add("- 市场主线：$(Get-LatestReport -Pattern "market_theme_*.md")")
    $lines.Add("- 最终候选池：$(Get-LatestReport -Pattern "research_candidates_*.md")")
    $lines.Add("- 每日复盘：$(Get-LatestReport -Pattern "daily_research_summary_*.md")")
    $lines.Add("")
    $lines.Add("这份报告只说明数据准备状态，不构成买卖建议。")

    $lines -join "`n" | Set-Content -LiteralPath $reportPath -Encoding UTF8
    if (-not $CheckpointOnly) {
        Copy-Item -LiteralPath $reportPath -Destination $currentPath -Force
    }
    Write-Step "Nightly prep report: $reportPath"
}

Set-Location $ProjectRoot

$script:StepResults = @()
$script:FinalStaleCount = "未知"
$script:FinalIndexStaleCount = "未知"
$script:ResolvedTargetDate = ""

$logDir = Join-Path $ProjectRoot "logs/nightly_prep"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$script:LogPath = Join-Path $logDir ("nightly_prep_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
Start-Transcript -Path $script:LogPath -Append | Out-Null

try {
    Write-Step "Nightly research prep started. ProjectRoot: $ProjectRoot"

    $today = Get-Date
    $hasExplicitTargetDate = -not [string]::IsNullOrWhiteSpace($TargetDate)
    if (-not $Force -and -not $hasExplicitTargetDate -and ($today.DayOfWeek -eq "Saturday" -or $today.DayOfWeek -eq "Sunday")) {
        $script:ResolvedTargetDate = Resolve-DefaultDataDate -CutoffTime $ReportCutoffTime
        Add-StepResult -Name "周末检查" -Status "跳过" -Detail "周末默认不跑，使用 -Force 可强制执行。"
        Save-PrepReport -Status "跳过" -Detail "周末默认不跑。"
        return
    }

    $script:ResolvedTargetDate = if ($hasExplicitTargetDate) {
        Normalize-DateString -Value $TargetDate
    } else {
        Resolve-DefaultDataDate -CutoffTime $ReportCutoffTime
    }
    Write-Step "Data target date: $script:ResolvedTargetDate"

    $venvPython = Join-Path $ProjectRoot ".venv/Scripts/python.exe"
    if (Test-Path $venvPython) {
        $script:PythonExe = $venvPython
    } else {
        $script:PythonExe = "python"
    }
    $env:PYTHONPATH = (Join-Path $ProjectRoot "src") + [IO.Path]::PathSeparator + $env:PYTHONPATH

    $dataSyncScript = Join-Path $ProjectRoot "scripts/run_data_sync.ps1"
    $dataReady = $false
    $attemptLimit = [Math]::Max(1, $MaxSyncAttempts)
    for ($attempt = 1; $attempt -le $attemptLimit; $attempt++) {
        Invoke-ScriptStep -Name "补日线行情($attempt/$attemptLimit)" -Arguments @(
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", $dataSyncScript,
            "-ProjectRoot", $ProjectRoot,
            "-UniverseFile", $UniverseFile,
            "-Since", $Since,
            "-TargetDate", $script:ResolvedTargetDate,
            "-StockProvider", $StockProvider,
            "-FallbackStockProvider", $FallbackStockProvider,
            "-Workers", $Workers.ToString([Globalization.CultureInfo]::InvariantCulture),
            "-FallbackWorkers", $FallbackStockWorkers.ToString([Globalization.CultureInfo]::InvariantCulture),
            "-SleepSeconds", $SleepSeconds.ToString([Globalization.CultureInfo]::InvariantCulture),
            "-LookbackDays", $LookbackDays.ToString([Globalization.CultureInfo]::InvariantCulture)
        )

        Invoke-QuantStep -Name "数据覆盖复查($attempt/$attemptLimit)" -Arguments @(
            "cache-date-status",
            "--universe-file", $UniverseFile,
            "--target-date", $script:ResolvedTargetDate,
            "--exact-target-date",
            "--show-stale",
            "--top", "30",
            "--output-stale", "data/universe/stale_after_nightly.csv"
        )
        $script:FinalStaleCount = Get-CsvDataRowCount -Path (Join-Path $ProjectRoot "data/universe/stale_after_nightly.csv")
        if ($Force -or ([int]$script:FinalStaleCount) -le $MaxStaleAllowed) {
            $dataReady = $true
            break
        }

        if ($attempt -lt $attemptLimit) {
            $detail = "过期标的 $script:FinalStaleCount 只，超过阈值 $MaxStaleAllowed；等待 $RetryWaitMinutes 分钟后重试。"
            Add-StepResult -Name "等待行情更新($attempt/$attemptLimit)" -Status "等待" -Detail $detail
            Save-PrepReport -Status "行情准备中" -Detail $detail -CheckpointOnly
            Write-Step $detail
            Start-Sleep -Seconds ([Math]::Max(1, $RetryWaitMinutes) * 60)
        }
    }

    if (-not $dataReady) {
        $detail = "重试 $attemptLimit 轮后仍有过期标的 $script:FinalStaleCount 只，超过阈值 $MaxStaleAllowed；跳过形态、情绪、公告和荐股报告，避免用不完整行情生成结论。"
        Add-StepResult -Name "慢准备门槛" -Status "跳过" -Detail $detail
        Save-PrepReport -Status "行情未就绪" -Detail $detail
        Write-Step $detail
        return
    }
    if (([int]$script:FinalStaleCount) -gt 0) {
        Add-StepResult -Name "慢准备门槛" -Status "继续" -Detail "仍有 $script:FinalStaleCount 只标的无目标日K线（可能停牌、退市或源端缺失），未超过阈值 $MaxStaleAllowed；精确日期扫描会自动排除。"
    } else {
        Add-StepResult -Name "慢准备门槛" -Status "通过" -Detail "全市场缓存已到目标日期。"
    }

    if ($IndexSymbols.Count -gt 0) {
        $indexArgs = @(
            "sync-daily",
            "--symbols"
        ) + $IndexSymbols + @(
            "--since", $Since,
            "--until", $script:ResolvedTargetDate,
            "--asset-type", "etf",
            "--etf-provider", $EtfProvider,
            "--adjust", "none",
            "--incremental",
            "--lookback-days", $LookbackDays.ToString([Globalization.CultureInfo]::InvariantCulture),
            "--retries", "3",
            "--retry-wait", "1"
        )

        $primaryIndexSyncOk = $true
        try {
            Invoke-QuantStep -Name "补ETF指数行情" -Arguments $indexArgs
        } catch {
            $primaryIndexSyncOk = $false
            Write-Step ("Primary ETF provider failed: " + $_.Exception.Message)
        }

        $staleIndexSymbols = @(Get-IndexStaleSymbols -Symbols $IndexSymbols -TargetDate $script:ResolvedTargetDate)
        if ((-not $primaryIndexSyncOk -or $staleIndexSymbols.Count -gt 0) -and $FallbackEtfProvider -and $FallbackEtfProvider -ne $EtfProvider) {
            $fallbackSymbols = if ($staleIndexSymbols.Count -gt 0) { $staleIndexSymbols } else { $IndexSymbols }
            $fallbackArgs = @(
                "sync-daily",
                "--symbols"
            ) + $fallbackSymbols + @(
                "--since", $Since,
                "--until", $script:ResolvedTargetDate,
                "--asset-type", "etf",
                "--etf-provider", $FallbackEtfProvider,
                "--adjust", "none",
                "--incremental",
                "--lookback-days", $LookbackDays.ToString([Globalization.CultureInfo]::InvariantCulture),
                "--retries", "3",
                "--retry-wait", "1"
            )
            try {
                Invoke-QuantStep -Name "补ETF指数行情备用源" -Arguments $fallbackArgs
            } catch {
                Write-Step ("Fallback ETF provider failed: " + $_.Exception.Message)
            }
        }

        $finalIndexStale = @(Get-IndexStaleSymbols -Symbols $IndexSymbols -TargetDate $script:ResolvedTargetDate)
        $script:FinalIndexStaleCount = $finalIndexStale.Count
        if ($finalIndexStale.Count -gt 0) {
            Add-StepResult -Name "ETF指数覆盖复查" -Status "警告" -Detail ("未到目标日期：" + ($finalIndexStale -join ", "))
        } else {
            Add-StepResult -Name "ETF指数覆盖复查" -Status "通过" -Detail "ETF/指数缓存已到目标日期。"
        }
    } else {
        $script:FinalIndexStaleCount = 0
        Add-StepResult -Name "ETF指数覆盖复查" -Status "跳过" -Detail "IndexSymbols 为空。"
    }

    Invoke-QuantStep -Name "扫描突破确认池" -Arguments @(
        "scan-pattern",
        "--pattern", "base_breakout_setup",
        "--target-date", $script:ResolvedTargetDate,
        "--top", "120",
        "--min-score", "50",
        "--stages", "watch", "near_breakout",
        "--min-amount-ma20", "100000000",
        "--require-positive-trend-slope",
        "--max-close-vs-trend", "0.25",
        "--filter-max-ret-20", "0.25"
    )
    Invoke-QuantStep -Name "扫描低位潜伏池" -Arguments @(
        "scan-pattern",
        "--pattern", "accumulation_setup",
        "--target-date", $script:ResolvedTargetDate,
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
    Invoke-QuantStep -Name "扫描强趋势回踩池" -Arguments @(
        "scan-pattern",
        "--pattern", "trend_pullback_setup",
        "--target-date", $script:ResolvedTargetDate,
        "--top", "120",
        "--min-score", "50",
        "--stages", "trend_pullback", "trend_resume",
        "--min-amount-ma20", "100000000",
        "--min-ret-60", "0.18",
        "--filter-max-ret-20", "0.18",
        "--max-volume-ratio", "3.20",
        "--max-close-vs-trend", "0.65",
        "--max-drawdown-from-high", "0.32"
    )
    Invoke-QuantStep -Name "扫描静默反转观察池" -Arguments @(
        "scan-pattern",
        "--pattern", "quiet_reversal_setup",
        "--target-date", $script:ResolvedTargetDate,
        "--top", "80",
        "--min-score", "55",
        "--min-amount-ma20", "100000000"
    )
    Invoke-QuantStep -Name "情绪面缓存" -Arguments @(
        "sentiment-score",
        "--latest-scan",
        "--target-date", $script:ResolvedTargetDate,
        "--top", $SentimentTop.ToString([Globalization.CultureInfo]::InvariantCulture),
        "--display-top", "30",
        "--news-days", "7",
        "--research-days", "90"
    )
    Invoke-QuantStep -Name "市场主线缓存" -Arguments @(
        "market-theme",
        "--target-date", $script:ResolvedTargetDate,
        "--top", "20"
    )
    $moneyFlowProbeStartedAt = Get-Date
    $moneyFlowTop = [Math]::Min(30, $SentimentTop)
    Invoke-QuantStep -Name "资金流核心候选探测" -Arguments @(
        "money-flow",
        "--latest-scan",
        "--target-date", $script:ResolvedTargetDate,
        "--top", $moneyFlowTop.ToString([Globalization.CultureInfo]::InvariantCulture),
        "--lookback-days", "10",
        "--display-top", "30",
        "--retries", "1",
        "--retry-wait", "0",
        "--sleep", "0.1",
        "--min-success-rate", "0.30",
        "--soft-fail"
    )
    $moneyFlowDateToken = ([datetime]::Parse($script:ResolvedTargetDate)).ToString("yyyyMMdd")
    $moneyFlowReport = Get-ChildItem -LiteralPath (Join-Path $ProjectRoot "reports") -Filter ("money_flow_{0}_*.csv" -f $moneyFlowDateToken) |
        Where-Object { $_.LastWriteTime -ge $moneyFlowProbeStartedAt.AddSeconds(-1) } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($null -eq $moneyFlowReport) {
        Add-StepResult -Name "资金流覆盖策略" -Status "降级" -Detail "核心候选探测未达到最低成功率，跳过全量抓取；候选池按资金流缺失继续。"
        Write-Step "Money-flow probe produced no valid report; continue without the optional factor."
    } else {
        Add-StepResult -Name "资金流覆盖策略" -Status "通过" -Detail ("已缓存核心候选：" + $moneyFlowReport.FullName)
    }
    Invoke-QuantStep -Name "巨潮风险事件缓存" -Arguments @(
        "risk-events",
        "--latest-scan",
        "--target-date", $script:ResolvedTargetDate,
        "--top", $SentimentTop.ToString([Globalization.CultureInfo]::InvariantCulture),
        "--days", $RiskDays.ToString([Globalization.CultureInfo]::InvariantCulture),
        "--display-top", "30"
    )
    Invoke-QuantStep -Name "候选池慢增强" -Arguments @(
        "research-candidates",
        "--target-date", $script:ResolvedTargetDate,
        "--top", "30",
        "--risk-days", $RiskDays.ToString([Globalization.CultureInfo]::InvariantCulture),
        "--fetch-profiles",
        "--fetch-notices"
    )
    Invoke-QuantStep -Name "归档研究快照" -Arguments @(
        "snapshot-research",
        "--target-date", $script:ResolvedTargetDate
    )
    Invoke-QuantStep -Name "生成每日复盘" -Arguments @(
        "daily-research-summary",
        "--target-date", $script:ResolvedTargetDate,
        "--top", "30"
    )
    Invoke-QuantStep -Name "生成结构化决策信号" -Arguments @(
        "decision-signals",
        "--target-date", $script:ResolvedTargetDate,
        "--top", "80"
    )
    Invoke-QuantStep -Name "生成基本面深研初选" -Arguments @(
        "fundamental-watchlist",
        "--target-date", $script:ResolvedTargetDate,
        "--top", "20"
    )
    Invoke-QuantStep -Name "财务质量硬筛" -Arguments @(
        "fundamental-quality-screen",
        "--target-date", $script:ResolvedTargetDate,
        "--top", "20",
        "--research-top", "5",
        "--workers", "4",
        "--refresh"
    )
    $reviewSince = ([datetime]::Parse($script:ResolvedTargetDate)).AddDays(-45).ToString("yyyy-MM-dd")
    Invoke-QuantStep -Name "生成策略滚动复盘" -Arguments @(
        "research-review",
        "--since", $reviewSince,
        "--until", $script:ResolvedTargetDate,
        "--top-movers", "20"
    )
    Invoke-QuantStep -Name "候选生命周期跟踪" -Arguments @(
        "track-candidates",
        "--since", $reviewSince,
        "--until", $script:ResolvedTargetDate,
        "--universe-file", $UniverseFile,
        "--top", "50"
    )
    Invoke-QuantStep -Name "股票池维表入库" -Arguments @(
        "warehouse-sync-universe",
        "--universe-file", $UniverseFile,
        "--target-date", $script:ResolvedTargetDate
    )
    Invoke-QuantStep -Name "日线行情入库" -Arguments @(
        "warehouse-sync-candles",
        "--universe-file", $UniverseFile,
        "--target-date", $script:ResolvedTargetDate
    )
    if ($IndexSymbols.Count -gt 0) {
        $closingStaleIndexSymbols = @(Get-IndexStaleSymbols -Symbols $IndexSymbols -TargetDate $script:ResolvedTargetDate)
        if ($closingStaleIndexSymbols.Count -gt 0) {
            $closingProvider = if ($FallbackEtfProvider) { $FallbackEtfProvider } else { $EtfProvider }
            $closingIndexArgs = @(
                "sync-daily",
                "--symbols"
            ) + $closingStaleIndexSymbols + @(
                "--since", $Since,
                "--until", $script:ResolvedTargetDate,
                "--asset-type", "etf",
                "--etf-provider", $closingProvider,
                "--adjust", "none",
                "--incremental",
                "--lookback-days", $LookbackDays.ToString([Globalization.CultureInfo]::InvariantCulture),
                "--retries", "3",
                "--retry-wait", "1"
            )
            try {
                Invoke-QuantStep -Name "ETF指数收尾补数" -Arguments $closingIndexArgs
            } catch {
                Write-Step ("Closing ETF retry failed: " + $_.Exception.Message)
            }
        }
        $closingStaleIndexSymbols = @(Get-IndexStaleSymbols -Symbols $IndexSymbols -TargetDate $script:ResolvedTargetDate)
        $script:FinalIndexStaleCount = $closingStaleIndexSymbols.Count
        if ($closingStaleIndexSymbols.Count -gt 0) {
            Add-StepResult -Name "ETF指数收尾复查" -Status "警告" -Detail ("源端仍未提供目标日行情：" + ($closingStaleIndexSymbols -join ", "))
        } else {
            Add-StepResult -Name "ETF指数收尾复查" -Status "通过" -Detail "ETF/指数在入仓前均已到目标日期。"
        }
        $indexWarehouseArgs = @(
            "warehouse-sync-candles",
            "--symbols"
        ) + $IndexSymbols + @(
            "--target-date", $script:ResolvedTargetDate
        )
        Invoke-QuantStep -Name "指数日线入库" -Arguments $indexWarehouseArgs
    }
    Invoke-QuantStep -Name "研究快照回填" -Arguments @(
        "warehouse-backfill-snapshots",
        "--since", $script:ResolvedTargetDate,
        "--until", $script:ResolvedTargetDate
    )
    $manifestParameters = [ordered]@{
        workflow = "nightly_prep"
        target_date = $script:ResolvedTargetDate
        stock_provider = $StockProvider
        fallback_stock_provider = $FallbackStockProvider
        workers = $Workers
        lookback_days = $LookbackDays
        sentiment_top = $SentimentTop
        risk_days = $RiskDays
        fundamental_quality = "top=20,research_top=5,workers=4,point_in_time=true"
        base_scan = "top=120,min_score=50,max_close_vs_trend=0.25,max_ret20=0.25"
        accumulation_scan = "top=120,min_score=50,base_window=250,max_ret20=0.15,max_ret60=0.30,max_position=0.82"
        trend_scan = "top=120,min_score=50,min_ret60=0.18,max_ret20=0.18,max_drawdown=0.32"
    } | ConvertTo-Json -Compress
    $manifestParametersPath = Join-Path $ProjectRoot "logs/nightly_run_parameters.json"
    $manifestParameters | Set-Content -LiteralPath $manifestParametersPath -Encoding UTF8
    Invoke-QuantStep -Name "研究仓库入库" -Arguments @(
        "warehouse-ingest",
        "--target-date", $script:ResolvedTargetDate,
        "--parameters-file", $manifestParametersPath
    )
    Invoke-QuantStep -Name "影子组合收盘估值" -Arguments @(
        "shadow-evaluate",
        "--until", $script:ResolvedTargetDate
    )
    Invoke-QuantStep -Name "现有因子证据更新" -Arguments @(
        "factor-evidence",
        "--until", $script:ResolvedTargetDate,
        "--horizon", "5d",
        "--quantiles", "5"
    )

    Save-PrepReport -Status "成功"
    Write-Step "Nightly research prep completed. Log: $script:LogPath"
} catch {
    Save-PrepReport -Status "失败" -Detail $_.Exception.Message
    Write-Step ("Nightly research prep failed: " + $_.Exception.Message)
    throw
} finally {
    Stop-Transcript | Out-Null
}
