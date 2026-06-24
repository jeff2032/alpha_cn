param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$UniverseFile = "data/universe/a_stock.csv",
    [string]$Since = "2020-01-01",
    [string]$TargetDate = "",
    [string]$PlanDate = "",
    [string]$ReportCutoffTime = "15:30",
    [double]$SleepSeconds = 0.2,
    [int]$Workers = 6,
    [int]$LookbackDays = 60,
    [string]$ProbeSymbol = "000001",
    [string]$ObsidianVaultPath = "G:\Program Files (x86)\Obsidian_base",
    [string]$ObsidianExportDir = "中国A股荐股",
    [switch]$NoObsidianExport,
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
        throw "Command failed, exit code: $LASTEXITCODE"
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

function Get-PreviousWeekday {
    param([datetime]$Date)

    $day = $Date.Date
    while ($day.DayOfWeek -eq "Saturday" -or $day.DayOfWeek -eq "Sunday") {
        $day = $day.AddDays(-1)
    }
    return $day
}

function Resolve-CachedTradingDate {
    param([datetime]$Date)

    $cacheDir = Join-Path $ProjectRoot "data/cache/akshare/daily"
    if (-not (Test-Path $cacheDir)) {
        return (Get-PreviousWeekday -Date $Date).ToString("yyyy-MM-dd")
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

    $target = $Date.Date
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

function Resolve-DefaultDataDate {
    param([string]$CutoffTime)

    $candidate = Get-DefaultTargetDate -CutoffTime $CutoffTime
    $resolved = Resolve-CachedTradingDate -Date ([datetime]$candidate)
    if ($resolved -ne $candidate) {
        Write-Step "Default target $candidate is not a cached trading date; use $resolved."
    }
    return $resolved
}

function Get-DefaultPlanDate {
    param(
        [string]$DataDate,
        [string]$CutoffTime
    )

    $now = Get-Date
    $cutoff = [TimeSpan]::Parse($CutoffTime)
    if ($now.TimeOfDay -lt $cutoff) {
        return (Get-PreviousWeekday -Date $now.Date).ToString("yyyy-MM-dd")
    }
    return $DataDate
}

function Normalize-DateString {
    param([string]$Value)

    try {
        return ([datetime]$Value).ToString("yyyy-MM-dd")
    } catch {
        throw "Invalid date: $Value. Expected format like 2026-06-17."
    }
}

function Resolve-TargetDateString {
    param([string]$Value)

    $normalized = Normalize-DateString -Value $Value
    $resolved = Resolve-CachedTradingDate -Date ([datetime]$normalized)
    if ($resolved -ne $normalized) {
        Write-Step "Requested target $normalized is not a cached trading date; use $resolved."
    }
    return $resolved
}

function Copy-LatestMarkdownReport {
    param(
        [string]$Pattern,
        [string]$DestinationName,
        [string]$TargetDir
    )

    $reportsDir = Join-Path $ProjectRoot "reports"
    $source = Get-ChildItem -LiteralPath $reportsDir -Filter $Pattern |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($null -eq $source) {
        Write-Step "Obsidian export skipped, no report matched: $Pattern"
        return
    }

    $destination = Join-Path $TargetDir $DestinationName
    Copy-Item -LiteralPath $source.FullName -Destination $destination -Force
    Write-Step "Obsidian export: $($source.Name) -> $destination"
}

function Get-LatestReportFile {
    param([string]$Pattern)

    $reportsDir = Join-Path $ProjectRoot "reports"
    return Get-ChildItem -LiteralPath $reportsDir -Filter $Pattern |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
}

function Format-CandidateTable {
    param([object[]]$Rows)

    $items = @($Rows)
    if ($items.Count -eq 0) {
        return "- 暂无"
    }

    $lines = @(
        "| 代码 | 名称 | 分层 | 研究分 | 主题簇 | 阶段 | 节奏 | 扣分 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |"
    )
    foreach ($row in $items) {
        $score = ""
        $penalty = ""
        try { $score = ([math]::Round([double]$row.research_score, 2)).ToString([Globalization.CultureInfo]::InvariantCulture) } catch {}
        try { $penalty = ([math]::Round([double]$row.total_penalty, 2)).ToString([Globalization.CultureInfo]::InvariantCulture) } catch {}
        $lines += "| $($row.symbol) | $($row.name) | $($row.research_tier) | $score | $($row.theme_cluster) | $($row.stage) | $($row.setup_phase) | $penalty |"
    }
    return ($lines -join "`r`n")
}

function Format-ThemeTable {
    param([object[]]$Rows)

    $items = @($Rows)
    if ($items.Count -eq 0) {
        return "- 暂无"
    }

    $lines = @(
        "| 主题 | 候选数 | 涨停数 | 强势数 | 主题分 |",
        "| --- | --- | --- | --- | --- |"
    )
    foreach ($row in $items) {
        $score = ""
        try { $score = ([math]::Round([double]$row.theme_score, 2)).ToString([Globalization.CultureInfo]::InvariantCulture) } catch {}
        $lines += "| $($row.theme) | $($row.stock_count) | $($row.limit_count) | $($row.strong_count) | $score |"
    }
    return ($lines -join "`r`n")
}

function New-PreMarketPlanReport {
    param(
        [string]$TargetDir,
        [string]$ReportDate,
        [string]$DataDate
    )

    $dateStamp = $DataDate -replace "-", ""
    $summary = Get-LatestReportFile -Pattern "daily_research_summary_${dateStamp}_*.md"
    $candidateCsv = Get-LatestReportFile -Pattern "daily_research_candidates_${dateStamp}_*.csv"
    if ($null -eq $candidateCsv) {
        $candidateCsv = Get-LatestReportFile -Pattern "research_candidates_${dateStamp}_*.csv"
    }
    $themeCsv = Get-LatestReportFile -Pattern "market_theme_${dateStamp}_*.csv"

    $marketLine = "- 市场温度：待查看当天复盘"
    $actionLine = "- 操作口径：先看候选分层，再结合开盘强弱确认"
    if ($summary) {
        $summaryLines = Get-Content -LiteralPath $summary.FullName
        $foundMarket = $summaryLines | Where-Object { $_ -like "- 市场温度：*" } | Select-Object -First 1
        $foundAction = $summaryLines | Where-Object { $_ -like "- 操作口径：*" } | Select-Object -First 1
        if ($foundMarket) { $marketLine = $foundMarket }
        if ($foundAction) { $actionLine = $foundAction }
    }

    $themes = @()
    if ($themeCsv) {
        $themes = @(Import-Csv -LiteralPath $themeCsv.FullName | Select-Object -First 10)
    }

    $candidates = @()
    if ($candidateCsv) {
        $candidates = @(Import-Csv -LiteralPath $candidateCsv.FullName)
    }
    $a12 = @($candidates | Where-Object { $_.research_tier -in @("A1", "A2") } | Select-Object -First 12)
    $a3 = @($candidates | Where-Object { $_.research_tier -eq "A3" } | Select-Object -First 18)
    $watch = @($candidates | Where-Object { $_.research_tier -in @("B1", "B2") } | Select-Object -First 12)

    $planPath = Join-Path $TargetDir "$ReportDate.md"
    $dataReviewLink = "../每日复盘/$DataDate/每日推荐复盘.md"
    $candidateLink = "../每日复盘/$DataDate/最终候选池.md"

    @"
# 开盘前推荐计划

计划日期：$ReportDate
数据截至：$DataDate

这份是次日开盘前计划，不是 $DataDate 当天复盘。完整当天复盘见：[$DataDate 每日推荐复盘]($dataReviewLink)，候选明细见：[$DataDate 最终候选池]($candidateLink)。

## 市场口径

$marketLine
$actionLine

## 重点主线

$(Format-ThemeTable -Rows $themes)

## A1/A2 潜伏与启动

看 3-5 个交易日是否转强，不用单日涨跌否定。

$(Format-CandidateTable -Rows $a12)

## A3 主线趋势

看 1-2 个交易日趋势延续和回踩不破，避免高开过热追买。

$(Format-CandidateTable -Rows $a3)

## B1/B2 观察补票

只做人工复盘和主线补票，不直接当作买点。

$(Format-CandidateTable -Rows $watch)

## 风险口径

- 高开过多、放量滞涨、冲高回落的票先观察，不追。
- 有公告风险、减持、问询、低流动性或疑似复权/特殊事件的样本，只做复盘，不纳入常规决策。
- A3 当前弹性最好，但波动也最大；A1/A2 更偏潜伏，需要给 3-5 日验证窗口。

这份文档只做研究复盘，不构成买卖建议。
"@ | Set-Content -LiteralPath $planPath -Encoding UTF8

    Write-Step "Obsidian export: created pre-market plan -> $planPath"
}

function Export-DailyReportsToObsidian {
    param(
        [string]$ReportDate,
        [string]$DataDate
    )

    if ($NoObsidianExport) {
        Write-Step "Obsidian export skipped by -NoObsidianExport."
        return
    }
    if (-not $ObsidianVaultPath) {
        Write-Step "Obsidian export skipped, ObsidianVaultPath is empty."
        return
    }
    if (-not (Test-Path -LiteralPath $ObsidianVaultPath)) {
        Write-Step "Obsidian export skipped, vault not found: $ObsidianVaultPath"
        return
    }

    $exportRoot = Join-Path $ObsidianVaultPath $ObsidianExportDir
    $reviewRoot = Join-Path $exportRoot "每日复盘"
    $planRoot = Join-Path $exportRoot "开盘计划"
    $strategyRoot = Join-Path $exportRoot "策略迭代"
    New-Item -ItemType Directory -Force -Path $reviewRoot, $planRoot, $strategyRoot | Out-Null

    $dateStamp = $DataDate -replace "-", ""
    $dataDir = Join-Path $reviewRoot $DataDate
    New-Item -ItemType Directory -Force -Path $dataDir | Out-Null

    $indexPath = Join-Path $exportRoot "README.md"
    @"
# 中国A股荐股

这个目录由 alpha_cn 研究流程同步生成。

## 怎么看

- `开盘计划/YYYY-MM-DD.md`：早上最先看的一页纸，给当天开盘前使用。
- `每日复盘/YYYY-MM-DD/`：收盘后按数据日归档的完整复盘材料。
- `策略迭代/`：长期沉淀规则复盘、miss 样本反推和风险过滤。

## 日期口径

- 每日复盘日期 = 数据截至日期，例如 `每日复盘/2026-06-22/`。
- 开盘计划日期 = 准备交易的日期，例如 `开盘计划/2026-06-23.md`，内容基于上一交易日数据。
"@ | Set-Content -LiteralPath $indexPath -Encoding UTF8

    Copy-LatestMarkdownReport -Pattern "daily_research_summary_${dateStamp}_*.md" -DestinationName "每日推荐复盘.md" -TargetDir $dataDir
    Copy-LatestMarkdownReport -Pattern "research_candidates_${dateStamp}_*.md" -DestinationName "最终候选池.md" -TargetDir $dataDir
    Copy-LatestMarkdownReport -Pattern "market_theme_${dateStamp}_*.md" -DestinationName "市场主线.md" -TargetDir $dataDir
    Copy-LatestMarkdownReport -Pattern "sentiment_watchlist_${dateStamp}_*.md" -DestinationName "情绪观察.md" -TargetDir $dataDir
    Copy-LatestMarkdownReport -Pattern "research_review_${dateStamp}_*.md" -DestinationName "滚动复盘.md" -TargetDir $dataDir

    $reflectionPath = Join-Path $dataDir "策略反思.md"
    if (-not (Test-Path -LiteralPath $reflectionPath)) {
        @"
# 策略反思

计划日期：$DataDate
数据截至：$DataDate

## 今日候选反馈

- 

## 命中与错过

- 

## 规则调整

- 

## 明日观察

- 
"@ | Set-Content -LiteralPath $reflectionPath -Encoding UTF8
        Write-Step "Obsidian export: created reflection note -> $reflectionPath"
    }

    if ($ReportDate -ne $DataDate) {
        New-PreMarketPlanReport -TargetDir $planRoot -ReportDate $ReportDate -DataDate $DataDate
    }
}

Set-Location $ProjectRoot

$logDir = Join-Path $ProjectRoot "logs/daily_research"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logPath = Join-Path $logDir ("daily_research_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
Start-Transcript -Path $logPath -Append | Out-Null

try {
    Write-Step "Daily research task started. ProjectRoot: $ProjectRoot"

    $today = Get-Date
    $hasExplicitTargetDate = -not [string]::IsNullOrWhiteSpace($TargetDate)
    $hasExplicitPlanDate = -not [string]::IsNullOrWhiteSpace($PlanDate)
    if (-not $Force -and -not $hasExplicitTargetDate -and -not $hasExplicitPlanDate -and ($today.DayOfWeek -eq "Saturday" -or $today.DayOfWeek -eq "Sunday")) {
        Write-Step "Weekend detected, skip."
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
        throw "Universe file not found: $universePath"
    }

    $targetDate = if ($hasExplicitTargetDate) {
        Resolve-TargetDateString -Value $TargetDate
    } else {
        Resolve-DefaultDataDate -CutoffTime $ReportCutoffTime
    }
    $planDate = if ($hasExplicitPlanDate) {
        Normalize-DateString -Value $PlanDate
    } else {
        Get-DefaultPlanDate -DataDate $targetDate -CutoffTime $ReportCutoffTime
    }
    Write-Step "Data target date: $targetDate"
    Write-Step "Plan/output date: $planDate"
    $probeBefore = Get-CacheLastDate -Symbol $ProbeSymbol
    Write-Step "Probe $ProbeSymbol last date before sync: $probeBefore"
    Invoke-Quant @(
        "sync-daily",
        "--symbols", $ProbeSymbol,
        "--since", $Since,
        "--adjust", "qfq",
        "--asset-type", "stock",
        "--stock-provider", "sina",
        "--incremental",
        "--lookback-days", $LookbackDays.ToString([Globalization.CultureInfo]::InvariantCulture)
    )
    $probeAfter = Get-CacheLastDate -Symbol $ProbeSymbol
    Write-Step "Probe $ProbeSymbol last date after sync: $probeAfter"

    if (-not $Force -and (-not $probeAfter -or ([datetime]$probeAfter) -lt ([datetime]$targetDate))) {
        $latestCacheDate = Get-LatestCacheDate
        if ($latestCacheDate -and ([datetime]$latestCacheDate) -lt ([datetime]$targetDate)) {
            Write-Step "Data source is not updated to $targetDate. Fall back to latest cached trading date $latestCacheDate."
            $targetDate = $latestCacheDate
            if (-not $hasExplicitPlanDate) {
                $planDate = Get-DefaultPlanDate -DataDate $targetDate -CutoffTime $ReportCutoffTime
            }
        } else {
            Write-Step "Data source is not updated to $targetDate yet. Skip universe sync and research reports."
            return
        }
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
    Write-Step "Stale symbols: $staleCount"
    if ($staleCount -gt 0) {
        $effectiveWorkers = $Workers
        if ($effectiveWorkers -gt 2) {
            $effectiveWorkers = 2
            Write-Step "Sina provider is unstable with high parallelism; use effective workers $effectiveWorkers instead of $Workers."
        }
        Invoke-Quant @(
            "sync-stock-universe",
            "--universe-file", "data/universe/stale.csv",
            "--since", $Since,
            "--stock-provider", "sina",
            "--adjust", "qfq",
            "--sleep", $SleepSeconds.ToString([Globalization.CultureInfo]::InvariantCulture),
            "--workers", $effectiveWorkers.ToString([Globalization.CultureInfo]::InvariantCulture),
            "--incremental",
            "--lookback-days", $LookbackDays.ToString([Globalization.CultureInfo]::InvariantCulture),
            "--no-skip-existing"
        )
    }

    $latestCacheDate = Get-LatestCacheDate
    if (-not $latestCacheDate) {
        throw "Unable to infer latest trading date from cache."
    }
    if (-not $Force -and ([datetime]$latestCacheDate) -lt ([datetime]$targetDate)) {
        Write-Step "Latest cache date $latestCacheDate is earlier than target date $targetDate. Skip research reports."
        return
    }
    Write-Step "Latest cache date: $latestCacheDate"

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
        "scan-pattern",
        "--pattern", "trend_pullback_setup",
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
    Invoke-Quant @(
        "sentiment-score",
        "--latest-scan",
        "--target-date", $targetDate,
        "--top", "90",
        "--display-top", "30",
        "--news-days", "7",
        "--research-days", "90"
    )
    Invoke-Quant @(
        "market-theme",
        "--target-date", $targetDate,
        "--top", "20"
    )
    Invoke-Quant @(
        "research-candidates",
        "--target-date", $targetDate,
        "--top", "30",
        "--no-fetch-profiles",
        "--no-fetch-notices"
    )
    Invoke-Quant @(
        "snapshot-research",
        "--target-date", $targetDate
    )
    Invoke-Quant @(
        "daily-research-summary",
        "--target-date", $targetDate,
        "--top", "30"
    )

    Export-DailyReportsToObsidian -ReportDate $planDate -DataDate $targetDate

    Write-Step "Daily research task completed. Log: $logPath"
} catch {
    Write-Step ("Daily research task failed: " + $_.Exception.Message)
    throw
} finally {
    Stop-Transcript | Out-Null
}
