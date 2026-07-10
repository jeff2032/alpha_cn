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
    [switch]$ExportOnly,
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

function Get-NextWeekday {
    param([datetime]$Date)

    $day = $Date.Date
    while ($day.DayOfWeek -eq "Saturday" -or $day.DayOfWeek -eq "Sunday") {
        $day = $day.AddDays(1)
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

function Resolve-NextPlanDate {
    param([string]$DataDate)

    $dataDay = ([datetime]$DataDate).Date
    $cacheDir = Join-Path $ProjectRoot "data/cache/akshare/daily"

    if (Test-Path $cacheDir) {
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

        $next = $null
        foreach ($key in $counts.Keys) {
            $candidate = [datetime]$key
            if ($counts[$key] -ge 100 -and $candidate -gt $dataDay) {
                if ($null -eq $next -or $candidate -lt $next) {
                    $next = $candidate
                }
            }
        }
        if ($null -ne $next) {
            return $next.ToString("yyyy-MM-dd")
        }
    }

    return (Get-NextWeekday -Date $dataDay.AddDays(1)).ToString("yyyy-MM-dd")
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

    return Resolve-NextPlanDate -DataDate $DataDate
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
        "| 代码 | 名称 | 分层 | 研究分 | 主题簇 | 阶段 | 节奏 | 扣分 | 风险 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"
    )
    foreach ($row in $items) {
        $score = ""
        $penalty = ""
        try { $score = ([math]::Round([double]$row.research_score, 2)).ToString([Globalization.CultureInfo]::InvariantCulture) } catch {}
        try { $penalty = ([math]::Round([double]$row.total_penalty, 2)).ToString([Globalization.CultureInfo]::InvariantCulture) } catch {}
        $lines += "| $($row.symbol) | $($row.name) | $($row.research_tier) | $score | $($row.theme_cluster) | $($row.stage) | $($row.setup_phase) | $penalty | $($row.risk_level) |"
    }
    return ($lines -join "`r`n")
}

function Format-LifecycleTable {
    param([object[]]$Rows)

    $items = @($Rows)
    if ($items.Count -eq 0) {
        return "- 暂无"
    }

    $lines = @(
        "| 代码 | 名称 | 当前分组 | 结果 | 已走交易日 | 主观察日 | 3日收益 | 5日收益 | 10日收益 | 风险 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"
    )
    foreach ($row in $items) {
        $ret3 = Format-PercentText $row.ret_3d
        $ret5 = Format-PercentText $row.ret_5d
        $ret10 = Format-PercentText $row.ret_10d
        $lines += "| $($row.symbol) | $($row.name) | $($row.current_action_bucket) | $($row.result_label) | $($row.days_since_entry) | $($row.primary_horizon_days) | $ret3 | $ret5 | $ret10 | $($row.risk_level) |"
    }
    return ($lines -join "`r`n")
}

function Format-LifecycleEventTable {
    param([object[]]$Rows)

    $items = @($Rows)
    if ($items.Count -eq 0) {
        return "- 暂无"
    }

    $lines = @(
        "| 代码 | 名称 | 日状态 | 当日分组 | 分层 | 入池收益 | 入池最大浮盈 | 入池最大回撤 | 风险 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"
    )
    foreach ($row in $items) {
        $ret = Format-PercentText $row.since_entry_ret
        $high = Format-PercentText $row.since_entry_high_ret
        $low = Format-PercentText $row.since_entry_low_ret
        $lines += "| $($row.symbol) | $($row.name) | $($row.day_status) | $($row.action_bucket) | $($row.research_tier) | $ret | $high | $low | $($row.risk_level) |"
    }
    return ($lines -join "`r`n")
}

function Test-MinReturn {
    param(
        [object]$Value,
        [double]$MinValue
    )

    try {
        if ($null -eq $Value -or [string]::IsNullOrWhiteSpace([string]$Value)) {
            return $true
        }
        return ([double]$Value -ge $MinValue)
    } catch {
        return $true
    }
}

function Format-PercentText {
    param([object]$Value)

    try {
        if ($null -eq $Value -or [string]::IsNullOrWhiteSpace([string]$Value)) {
            return ""
        }
        $number = [double]$Value
        if ([double]::IsNaN($number)) {
            return ""
        }
        return (($number * 100).ToString("0.00", [Globalization.CultureInfo]::InvariantCulture) + "%")
    } catch {
        return ""
    }
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

function Format-CandidateDecisionCards {
    param(
        [object[]]$Rows,
        [string]$Mode = "main"
    )

    $items = @($Rows)
    if ($items.Count -eq 0) {
        return "- 暂无"
    }

    $lines = @()
    foreach ($row in $items) {
        $score = ""
        $penalty = ""
        try { $score = ([math]::Round([double]$row.research_score, 2)).ToString([Globalization.CultureInfo]::InvariantCulture) } catch {}
        try { $penalty = ([math]::Round([double]$row.total_penalty, 2)).ToString([Globalization.CultureInfo]::InvariantCulture) } catch {}
        $theme = if ([string]::IsNullOrWhiteSpace([string]$row.theme_cluster)) { "未命中主线" } else { $row.theme_cluster }
        $risk = if ([string]::IsNullOrWhiteSpace([string]$row.risk_tags)) { "无明显风险" } else { $row.risk_tags }
        $observe = if ($Mode -eq "upgrade") {
            "只看次日持续性、盘中承接和是否升级，不直接当买点。"
        } else {
            "看开盘承接、回踩不破和量能不过热。"
        }
        $invalid = if ($Mode -eq "upgrade") {
            "主线转弱、放量滞涨、冲高回落或风险标签加重。"
        } else {
            "高开过多后放量滞涨、跌破关键承接位或主线明显转弱。"
        }
        $lines += "### $($row.symbol) $($row.name)"
        $lines += ""
        $lines += "- 看点：$($row.research_tier) / $($row.action_bucket)，研究分 $score，主题 $theme，风险 $($row.risk_level)，扣分 $penalty。"
        $lines += "- 观察：$observe"
        $lines += "- 失效：$invalid"
        $lines += "- 风险：$risk"
        $lines += ""
    }
    return ($lines -join "`r`n")
}

function Format-LifecycleDecisionCards {
    param([object[]]$Rows)

    $items = @($Rows)
    if ($items.Count -eq 0) {
        return "- 暂无"
    }

    $lines = @()
    foreach ($row in $items) {
        $ret3 = Format-PercentText $row.ret_3d
        $ret5 = Format-PercentText $row.ret_5d
        $ret10 = Format-PercentText $row.ret_10d
        $returns = @()
        if ($ret3) { $returns += "3日 $ret3" }
        if ($ret5) { $returns += "5日 $ret5" }
        if ($ret10) { $returns += "10日 $ret10" }
        $returnText = if ($returns.Count -gt 0) { $returns -join "，" } else { "暂无完整收益窗口" }
        $lines += "### $($row.symbol) $($row.name)"
        $lines += ""
        $lines += "- 状态：$($row.current_action_bucket)，已走 $($row.days_since_entry)/$($row.primary_horizon_days) 个交易日，结果 $($row.result_label)。"
        $lines += "- 观察：仍在观察窗口内，重点看趋势承接和主线是否延续；$returnText。"
        $lines += "- 失效：回撤继续扩大、降级、命中失败标签或主线退潮。"
        $lines += ""
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
    $lifecycleCsv = Get-LatestReportFile -Pattern "candidate_lifecycles_${dateStamp}_*.csv"
    $lifecycleDailyCsv = Get-LatestReportFile -Pattern "candidate_lifecycle_daily_${dateStamp}_*.csv"

    $marketLine = "- 市场温度：待查看当天复盘"
    $actionLine = "- 操作口径：先看候选分层，再结合开盘强弱确认"
    if ($summary) {
        $summaryLines = Get-Content -LiteralPath $summary.FullName -Encoding UTF8
        $foundMarket = $summaryLines | Where-Object { $_ -like "- 市场温度：*" } | Select-Object -First 1
        $foundAction = $summaryLines | Where-Object { $_ -like "- 操作口径：*" } | Select-Object -First 1
        if ($foundMarket) { $marketLine = $foundMarket }
        if ($foundAction) { $actionLine = $foundAction }
    }

    $themes = @()
    if ($themeCsv) {
        $themes = @(Import-Csv -LiteralPath $themeCsv.FullName -Encoding UTF8 | Select-Object -First 10)
    }

    $candidates = @()
    if ($candidateCsv) {
        $candidates = @(Import-Csv -LiteralPath $candidateCsv.FullName -Encoding UTF8)
    }
    $mainBuckets = @("主攻-A2启动确认", "主攻-A3趋势延续")
    $mainAttack = @(
        $candidates |
            Where-Object { $_.action_bucket -in $mainBuckets -and $_.risk_level -in @("低", "中") } |
            Select-Object -First 5
    )
    if ($mainAttack.Count -eq 0) {
        $mainAttack = @($candidates | Where-Object { $_.research_tier -in @("A2", "A3") } | Select-Object -First 5)
    }

    $surgeWatchBuckets = @(
        "观察-B2s主线突发待确认",
        "补票-主线突发"
    )
    $surgeWatch = @(
        $candidates |
            Where-Object { $_.action_bucket -in $surgeWatchBuckets -and $_.risk_level -ne "高" } |
            Select-Object -First 8
    )

    $upgradeBuckets = @(
        "观察-A1低位潜伏",
        "观察-A3高波动",
        "观察-B2a主线扩散待升级",
        "补票-B2a主线扩散",
        "补票-B2强主题",
        "观察-B2b主题待确认"
    )
    $upgradeWatch = @(
        $candidates |
            Where-Object { $_.action_bucket -in $upgradeBuckets -and $_.risk_level -ne "高" } |
            Select-Object -First 10
    )

    $lifecycles = @()
    if ($lifecycleCsv) {
        $lifecycles = @(Import-Csv -LiteralPath $lifecycleCsv.FullName -Encoding UTF8)
    }
    $holdTracking = @(
        $lifecycles |
            Where-Object {
                $_.status -eq "active" -and
                $_.result_label -in @("pending", "neutral") -and
                $_.current_action_bucket -in @("主攻-A2启动确认", "主攻-A3趋势延续") -and
                $_.days_since_entry -gt 0 -and
                $_.risk_level -in @("低", "中") -and
                (Test-MinReturn $_.ret_3d -0.06) -and
                (Test-MinReturn $_.ret_5d -0.08)
            } |
            Sort-Object @{ Expression = { try { -[double]$_.current_score } catch { 0 } } } |
            Select-Object -First 5
    )
    $watchTracking = @(
        $lifecycles |
            Where-Object {
                $_.status -eq "active" -and
                $_.result_label -in @("pending", "neutral") -and
                $_.current_action_bucket -in @(
                    "观察-A1低位潜伏",
                    "观察-A3高波动",
                    "观察-B2a主线扩散待升级",
                    "观察-B2s主线突发待确认",
                    "补票-B2a主线扩散",
                    "补票-主线突发",
                    "补票-B2强主题",
                    "观察-B2b主题待确认"
                )
            } |
            Sort-Object @{ Expression = { try { -[double]$_.current_score } catch { 0 } } } |
            Select-Object -First 8
    )
    $changes = @()
    if ($lifecycleDailyCsv) {
        $changes = @(
            Import-Csv -LiteralPath $lifecycleDailyCsv.FullName -Encoding UTF8 |
                Where-Object { $_.target_date -eq $DataDate -and $_.day_status -in @("new", "upgraded", "downgraded") } |
                Sort-Object day_status, @{ Expression = { try { -[double]$_.research_score } catch { 0 } } } |
                Select-Object -First 15
        )
    }

    $planPath = Join-Path $TargetDir "$ReportDate.md"
    $digestLink = "../复盘摘要/$DataDate.md"

    @"
# $ReportDate 开盘决策

计划日期：$ReportDate
数据来源：$DataDate 收盘后

这份是给 $ReportDate 开盘前使用的决策页，只保留少量主攻、可继续观察和升级观察。完整内部报告仍保留在项目 reports/ 和数仓里。
$DataDate 的简短复盘见：[$DataDate 复盘摘要]($digestLink)。

## $DataDate 收盘市场口径

下面是 $DataDate 每日复盘里的市场温度和操作口径，用于 $ReportDate 开盘前参考；这不是 $ReportDate 盘中实时判断。

$marketLine
$actionLine

## $DataDate 收盘主线回顾

下面是 $DataDate 收盘后缓存的市场主线事实，用于 $ReportDate 开盘前参考；这不是 $ReportDate 的盘中实时主线，开盘后如果主线切换，以盘中强弱为准。

$(Format-ThemeTable -Rows $themes)

## $ReportDate 今日主攻

只放 A2 启动确认和主线仍强、风险干净的 A3 趋势延续。数量故意压缩，开盘后先看承接，不高开硬追。

$(Format-CandidateDecisionCards -Rows $mainAttack -Mode "main")

## $ReportDate 可稍微拿一拿（基于 $DataDate 生命周期跟踪）

这里不是新增推荐，只处理前几天入池后仍在观察窗口、还没命中或失败的主攻票。

$(Format-LifecycleDecisionCards -Rows $holdTracking)

## $ReportDate 短线机会和升级观察（基于 $DataDate 候选池）

B2s 单独承接低位主线突发观察；B2a/B2b 和 A1 是主题扩散或潜伏升级池，都不直接当买点。

### $ReportDate 主线突发观察

这里承接近期容易 miss 的低位主线突发样本。它们不是直接买点，必须等开盘承接、持续性和公告/情绪核验。

$(Format-CandidateDecisionCards -Rows $surgeWatch -Mode "upgrade")

### $ReportDate 主题扩散和潜伏观察

$(Format-CandidateDecisionCards -Rows $upgradeWatch -Mode "upgrade")

## $DataDate 旧票滚动状态

这里是 $DataDate 生命周期中间跟踪结果，只保留给我们判断旧池是否在变好或变坏。

### $DataDate 观察池状态

$(Format-LifecycleTable -Rows $watchTracking)

### $DataDate 生命周期变化

$(Format-LifecycleEventTable -Rows $changes)

## $ReportDate 风险和失效条件

- 高开过多、放量滞涨、冲高回落的票先观察，不追。
- 有公告风险、减持、问询、低流动性或疑似复权/特殊事件的样本，只做复盘，不纳入常规决策。
- 主攻 A3 必须主线仍强、低风险、低扣分、不过热、不拥挤；观察-A3高波动只看分歧承接，不追高。
- A2 看 3-15 日，A1 看 10-30 日；B2 只做升级观察，不能因为在观察池就直接当买点。

这份文档只做研究辅助，不构成买卖建议。
"@ | Set-Content -LiteralPath $planPath -Encoding UTF8

    Write-Step "Obsidian export: created pre-market plan -> $planPath"
}

function New-DailyReviewDigestReport {
    param(
        [string]$TargetDir,
        [string]$DataDate
    )

    $dateStamp = $DataDate -replace "-", ""
    $summary = Get-LatestReportFile -Pattern "daily_research_summary_${dateStamp}_*.md"
    $candidateCsv = Get-LatestReportFile -Pattern "daily_research_candidates_${dateStamp}_*.csv"
    if ($null -eq $candidateCsv) {
        $candidateCsv = Get-LatestReportFile -Pattern "research_candidates_${dateStamp}_*.csv"
    }
    $themeCsv = Get-LatestReportFile -Pattern "market_theme_${dateStamp}_*.csv"
    $reviewCsv = Get-LatestReportFile -Pattern "research_review_summary_${dateStamp}_*.csv"

    $marketLine = "- 市场温度：待查看当天复盘"
    $actionLine = "- 操作口径：先看候选分层，再结合开盘强弱确认"
    if ($summary) {
        $summaryLines = Get-Content -LiteralPath $summary.FullName -Encoding UTF8
        $foundMarket = $summaryLines | Where-Object { $_ -like "- 市场温度：*" } | Select-Object -First 1
        $foundAction = $summaryLines | Where-Object { $_ -like "- 操作口径：*" } | Select-Object -First 1
        if ($foundMarket) { $marketLine = $foundMarket }
        if ($foundAction) { $actionLine = $foundAction }
    }

    $themes = @()
    if ($themeCsv) {
        $themes = @(Import-Csv -LiteralPath $themeCsv.FullName -Encoding UTF8 | Select-Object -First 6)
    }

    $candidates = @()
    if ($candidateCsv) {
        $candidates = @(Import-Csv -LiteralPath $candidateCsv.FullName -Encoding UTF8)
    }
    $mainCount = @($candidates | Where-Object { $_.action_bucket -in @("主攻-A2启动确认", "主攻-A3趋势延续") }).Count
    $upgradeCount = @($candidates | Where-Object { $_.action_bucket -like "观察-B2*" -or $_.action_bucket -eq "观察-A1低位潜伏" }).Count
    $riskCount = @($candidates | Where-Object { $_.risk_level -in @("中高", "高") -or $_.action_bucket -eq "回避-风险优先" }).Count

    $reviewLine = "- 策略复盘：待查看滚动复盘"
    if ($reviewCsv) {
        $reviewRows = @(Import-Csv -LiteralPath $reviewCsv.FullName -Encoding UTF8)
        $a2 = $reviewRows | Where-Object { $_.table -eq "by_tier_horizon" -and $_.tier -eq "A2" -and $_.horizon -eq "5d" } | Select-Object -First 1
        $a3 = $reviewRows | Where-Object { $_.table -eq "by_tier_horizon" -and $_.tier -eq "A3" -and $_.horizon -eq "5d" } | Select-Object -First 1
        if ($a2 -or $a3) {
            $parts = @()
            if ($a2) { $parts += "A2 五日均值 $($a2.avg_ret)" }
            if ($a3) { $parts += "A3 五日均值 $($a3.avg_ret)" }
            $reviewLine = "- 策略复盘：" + ($parts -join "；")
        }
    }

    $digestPath = Join-Path $TargetDir "$DataDate.md"
    @"
# $DataDate 复盘摘要

数据日期：$DataDate

## 收盘口径

$marketLine
$actionLine

## 主线事实

$(Format-ThemeTable -Rows $themes)

## 候选压缩结果

- 主攻候选：$mainCount
- 升级观察：$upgradeCount
- 风险/回避样本：$riskCount

## 策略反馈

$reviewLine

详细候选、情绪、滚动复盘和生命周期明细保留在项目内部 reports/ 与数仓中；这页只给用户看结论。
"@ | Set-Content -LiteralPath $digestPath -Encoding UTF8

    Write-Step "Obsidian export: created review digest -> $digestPath"
}

function New-HoldingObservationReport {
    param(
        [string]$TargetDir,
        [string]$ReportDate,
        [string]$DataDate
    )

    $dateStamp = $DataDate -replace "-", ""
    $candidateCsv = Get-LatestReportFile -Pattern "daily_research_candidates_${dateStamp}_*.csv"
    if ($null -eq $candidateCsv) {
        $candidateCsv = Get-LatestReportFile -Pattern "research_candidates_${dateStamp}_*.csv"
    }
    $lifecycleCsv = Get-LatestReportFile -Pattern "candidate_lifecycles_${dateStamp}_*.csv"
    $holdingsPath = Join-Path $ProjectRoot "data/manual/holdings.csv"

    $candidates = @()
    if ($candidateCsv) {
        $candidates = @(Import-Csv -LiteralPath $candidateCsv.FullName -Encoding UTF8)
    }
    $lifecycles = @()
    if ($lifecycleCsv) {
        $lifecycles = @(Import-Csv -LiteralPath $lifecycleCsv.FullName -Encoding UTF8)
    }

    $holdingLines = @()
    if (-not (Test-Path -LiteralPath $holdingsPath)) {
        $holdingLines += "- 未找到持仓清单：data/manual/holdings.csv。"
        $holdingLines += "- 需要持仓辅助时，按 config/holdings.example.csv 建一个本地清单；data/ 不提交 git。"
    } else {
        $holdings = @(Import-Csv -LiteralPath $holdingsPath -Encoding UTF8)
        if ($holdings.Count -eq 0) {
            $holdingLines += "- 持仓清单为空。"
        }
        foreach ($holding in $holdings) {
            $symbol = [string]$holding.symbol
            $candidate = $candidates | Where-Object { $_.symbol -eq $symbol } | Select-Object -First 1
            $life = $lifecycles | Where-Object { $_.symbol -eq $symbol } | Select-Object -First 1
            $name = if ($holding.name) { $holding.name } elseif ($candidate) { $candidate.name } elseif ($life) { $life.name } else { $symbol }
            $bucket = if ($candidate) { $candidate.action_bucket } elseif ($life) { $life.current_action_bucket } else { "未进入候选/生命周期" }
            $risk = if ($candidate) { $candidate.risk_level } elseif ($life) { $life.risk_level } else { "未标注" }
            $tags = if ($candidate -and $candidate.risk_tags) { $candidate.risk_tags } else { "无明显风险标签" }
            $stance = "等反抽处理"
            if ($bucket -in @("主攻-A2启动确认", "主攻-A3趋势延续") -and $risk -in @("低", "中")) {
                $stance = "继续观察"
            } elseif ($risk -in @("中高", "高") -or $bucket -eq "回避-风险优先") {
                $stance = "风险退出观察"
            } elseif ($bucket -like "观察-B2*" -or $bucket -eq "观察-A1低位潜伏") {
                $stance = "减仓观察"
            }

            $costText = if ($holding.cost) { "，成本 $($holding.cost)" } else { "" }
            $holdingLines += "### $symbol $name"
            $holdingLines += ""
            $holdingLines += "- 当前口径：$stance。"
            $holdingLines += "- 原因：$bucket，风险 $risk$costText。"
            $holdingLines += "- 改善：重新进入主攻、放量承接、风险标签不加重。"
            $holdingLines += "- 失效：继续破位、反抽无量、主线转弱或公告风险加重。"
            $holdingLines += "- 风险：$tags"
            $holdingLines += ""
        }
    }

    $holdingPath = Join-Path $TargetDir "$ReportDate.md"
    @"
# $ReportDate 持仓观察

计划日期：$ReportDate
数据来源：$DataDate 收盘后

这页只处理已有持仓，不是新增推荐。输出口径用于观察和复盘，不构成买卖建议。

## 持仓处理

$($holdingLines -join "`r`n")
"@ | Set-Content -LiteralPath $holdingPath -Encoding UTF8

    Write-Step "Obsidian export: created holding observation -> $holdingPath"
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
    $decisionRoot = Join-Path $exportRoot "开盘决策"
    $holdingRoot = Join-Path $exportRoot "持仓观察"
    $digestRoot = Join-Path $exportRoot "复盘摘要"
    New-Item -ItemType Directory -Force -Path $decisionRoot, $holdingRoot, $digestRoot | Out-Null

    $dateStamp = $DataDate -replace "-", ""

    $indexPath = Join-Path $exportRoot "README.md"
    try {
        @"
# 中国A股荐股

这个目录由 alpha_cn 研究流程同步生成。

## 怎么看

- `开盘决策/YYYY-MM-DD.md`：每天早上最先看，只保留主攻、可继续观察、升级观察和风险条件。
- `持仓观察/YYYY-MM-DD.md`：只处理已有持仓，给出继续观察、减仓观察、等反抽处理或风险退出观察口径。
- `复盘摘要/YYYY-MM-DD.md`：收盘后按数据日归档的一页复盘摘要。

## 日期口径

- 复盘摘要日期 = 数据截至日期，例如 `复盘摘要/2026-06-22.md`。
- 开盘决策和持仓观察日期 = 准备交易的日期，例如 `开盘决策/2026-06-23.md`，内容基于上一交易日数据。
- 详细候选、情绪、滚动复盘和生命周期明细保留在项目内部 reports/ 与数仓中，不在 Obsidian 日常入口展开。
"@ | Set-Content -LiteralPath $indexPath -Encoding UTF8
    } catch {
        Write-Step "Obsidian export: README skipped, file is busy: $indexPath"
    }

    New-DailyReviewDigestReport -TargetDir $digestRoot -DataDate $DataDate

    if ($ReportDate -ne $DataDate) {
        New-PreMarketPlanReport -TargetDir $decisionRoot -ReportDate $ReportDate -DataDate $DataDate
        New-HoldingObservationReport -TargetDir $holdingRoot -ReportDate $ReportDate -DataDate $DataDate
    }
}

function Assert-ObsidianDailyOutputs {
    param(
        [string]$ReportDate,
        [string]$DataDate
    )

    if ($NoObsidianExport) { return }
    $exportRoot = Join-Path $ObsidianVaultPath $ObsidianExportDir
    $expected = @(
        (Join-Path $exportRoot "复盘摘要/$DataDate.md")
    )
    if ($ReportDate -ne $DataDate) {
        $expected += Join-Path $exportRoot "开盘决策/$ReportDate.md"
        $expected += Join-Path $exportRoot "持仓观察/$ReportDate.md"
    }
    $missing = @($expected | Where-Object { -not (Test-Path -LiteralPath $_) })
    if ($missing.Count -eq 0) {
        Write-Step "Obsidian output verification passed."
        return
    }

    $opsDir = Join-Path $ProjectRoot "reports/ops"
    New-Item -ItemType Directory -Force -Path $opsDir | Out-Null
    $alertPath = Join-Path $opsDir ("obsidian_missing_{0}.md" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
    $missingLines = $missing | ForEach-Object { "- $_" }
    @"
# Obsidian 输出缺失告警

- 数据日期：$DataDate
- 计划日期：$ReportDate
- 检查时间：$(Get-Date -Format "yyyy-MM-dd HH:mm:ss")

## 缺失文件

$($missingLines -join "`r`n")
"@ | Set-Content -LiteralPath $alertPath -Encoding UTF8
    throw "Obsidian output incomplete. Alert: $alertPath"
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
    if (-not $ExportOnly -and -not (Test-Path $universePath)) {
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
    if (([datetime]$planDate) -le ([datetime]$targetDate)) {
        Write-Step "WARNING: Plan/output date $planDate is not after data target date $targetDate. For a real pre-open plan, use -TargetDate as the previous trading day and -PlanDate as the next trading day."
    }

    if ($ExportOnly) {
        Write-Step "ExportOnly enabled; skip data sync and research generation."
        Invoke-Quant @(
            "research-pipeline",
            "--target-date", $targetDate,
            "--plan-date", $planDate,
            "--top", "30",
            "--signal-top", "80",
            "--fundamental-top", "20",
            "--no-write-warehouse"
        )
        Export-DailyReportsToObsidian -ReportDate $planDate -DataDate $targetDate
        Assert-ObsidianDailyOutputs -ReportDate $planDate -DataDate $targetDate
        Write-Step "ExportOnly completed. Log: $logPath"
        return
    }

    $probeBefore = Get-CacheLastDate -Symbol $ProbeSymbol
    Write-Step "Probe $ProbeSymbol last date before sync: $probeBefore"
    Invoke-Quant @(
        "sync-daily",
        "--symbols", $ProbeSymbol,
        "--since", $Since,
        "--until", $targetDate,
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
        try {
            Invoke-Quant @(
                "sync-stock-universe",
                "--universe-file", "data/universe/stale.csv",
                "--since", $Since,
                "--until", $targetDate,
                "--stock-provider", "sina",
                "--adjust", "qfq",
                "--sleep", $SleepSeconds.ToString([Globalization.CultureInfo]::InvariantCulture),
                "--workers", $effectiveWorkers.ToString([Globalization.CultureInfo]::InvariantCulture),
                "--incremental",
                "--lookback-days", $LookbackDays.ToString([Globalization.CultureInfo]::InvariantCulture),
                "--no-skip-existing"
            )
        } catch {
            if ($staleCount -le 100) {
                Write-Step "Universe sync failed for $staleCount stale symbols; continue with existing cache. Error: $($_.Exception.Message)"
            } else {
                throw
            }
        }
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
        "--target-date", $targetDate,
        "--top", "160",
        "--min-score", "45",
        "--stages", "watch", "near_breakout",
        "--min-amount-ma20", "100000000",
        "--require-positive-trend-slope",
        "--max-close-vs-trend", "0.25",
        "--filter-max-ret-20", "0.25"
    )
    Invoke-Quant @(
        "scan-pattern",
        "--pattern", "accumulation_setup",
        "--target-date", $targetDate,
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
        "--target-date", $targetDate,
        "--top", "160",
        "--min-score", "45",
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
        "research-pipeline",
        "--target-date", $targetDate,
        "--plan-date", $planDate,
        "--top", "30",
        "--signal-top", "80",
        "--fundamental-top", "20",
        "--no-write-warehouse"
    )
    $trackingSince = ([datetime]::Parse($targetDate)).AddDays(-45).ToString("yyyy-MM-dd")
    Invoke-Quant @(
        "research-review",
        "--since", $trackingSince,
        "--until", $targetDate,
        "--top-movers", "20"
    )
    Invoke-Quant @(
        "track-candidates",
        "--since", $trackingSince,
        "--until", $targetDate,
        "--universe-file", $UniverseFile,
        "--top", "80"
    )
    $manifestParameters = [ordered]@{
        workflow = "daily_decision"
        target_date = $targetDate
        plan_date = $planDate
        base_scan = "top=160,min_score=45,max_close_vs_trend=0.25,max_ret20=0.25"
        accumulation_scan = "top=120,min_score=50,base_window=250,max_ret20=0.15,max_ret60=0.30,max_position=0.82"
        trend_scan = "top=160,min_score=45,min_ret60=0.18,max_ret20=0.18,max_drawdown=0.32"
        signal_top = 80
        fundamental_top = 20
        review_days = 45
    } | ConvertTo-Json -Compress
    Invoke-Quant @(
        "warehouse-ingest",
        "--target-date", $targetDate,
        "--plan-date", $planDate,
        "--parameters-json", $manifestParameters
    )

    Export-DailyReportsToObsidian -ReportDate $planDate -DataDate $targetDate
    Assert-ObsidianDailyOutputs -ReportDate $planDate -DataDate $targetDate

    Write-Step "Daily research task completed. Log: $logPath"
} catch {
    Write-Step ("Daily research task failed: " + $_.Exception.Message)
    throw
} finally {
    Stop-Transcript | Out-Null
}
