param(
    [Parameter(Position = 0)]
    [ValidateSet("help", "task-status", "latest-ops", "obsidian-tree", "daily", "nightly", "warehouse-status", "data-loop", "retention-plan", "cache-status", "track-candidates")]
    [string]$Command = "help",

    [string]$TargetDate = "",
    [string]$PlanDate = "",
    [int]$Top = 10,
    [switch]$NoObsidianExport,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PythonExe = "python"
$VenvPython = Join-Path $ProjectRoot ".venv/Scripts/python.exe"
if (Test-Path -LiteralPath $VenvPython) {
    $PythonExe = $VenvPython
}

function Write-Section {
    param([string]$Title)
    Write-Host ""
    Write-Host "== $Title =="
}

function Invoke-Quant {
    param([string[]]$Arguments)

    Set-Location $ProjectRoot
    & $PythonExe -m quant_a_stock.cli @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "quant_a_stock.cli failed with exit code $LASTEXITCODE"
    }
}

function Show-Help {
    @"
alpha_cn Windows helper

Usage:
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\alpha.ps1 <command>

Commands:
  task-status       Show the Windows scheduled task status.
  latest-ops        Show recent nightly prep reports and daily reports.
  obsidian-tree     Show the Obsidian export folder layout.
  daily             Run the morning daily research workflow.
  nightly           Run the full nightly preparation workflow.
  warehouse-status  Show DuckDB/Parquet warehouse status.
  data-loop         Show data lifecycle and closed-loop status.
  retention-plan    Show cleanup dry-run candidates.
  cache-status      Show A-stock cache coverage.
  track-candidates  Build A1/A2/A3/B2 candidate lifecycle tracking.

Examples:
  .\scripts\alpha.ps1 task-status
  .\scripts\alpha.ps1 latest-ops
  .\scripts\alpha.ps1 obsidian-tree
  .\scripts\alpha.ps1 data-loop -TargetDate 2026-06-22 -PlanDate 2026-06-23
  .\scripts\alpha.ps1 retention-plan
  .\scripts\alpha.ps1 daily -TargetDate 2026-06-22 -PlanDate 2026-06-23
  .\scripts\alpha.ps1 cache-status -TargetDate 2026-06-22
  .\scripts\alpha.ps1 track-candidates -TargetDate 2026-06-24
"@
}

function Show-TaskStatus {
    $taskName = "AlphaCN Nightly Prep"
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($null -eq $task) {
        Write-Host "Scheduled task not found: $taskName"
        return
    }

    $info = Get-ScheduledTaskInfo -TaskName $taskName
    $trigger = $task.Triggers | Select-Object -First 1
    [pscustomobject]@{
        TaskName = $task.TaskName
        State = $task.State
        LastRunTime = $info.LastRunTime
        LastTaskResult = $info.LastTaskResult
        NextRunTime = $info.NextRunTime
        StartBoundary = $trigger.StartBoundary
        DaysInterval = $trigger.DaysInterval
        Action = (($task.Actions | ForEach-Object { ($_.Execute + " " + $_.Arguments).Trim() }) -join " || ")
    } | Format-List
}

function Show-LatestOps {
    Write-Section "Nightly Prep Reports"
    $opsDir = Join-Path $ProjectRoot "reports/ops"
    if (Test-Path -LiteralPath $opsDir) {
        Get-ChildItem -LiteralPath $opsDir -Filter "nightly_prep_*.md" |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First $Top Name, LastWriteTime, Length |
            Format-Table -AutoSize
    } else {
        Write-Host "No reports/ops directory."
    }

    Write-Section "Daily Research Reports"
    $reportsDir = Join-Path $ProjectRoot "reports"
    Get-ChildItem -LiteralPath $reportsDir -Filter "daily_research_summary_*.md" |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First $Top Name, LastWriteTime, Length |
        Format-Table -AutoSize

    Write-Section "Candidate Reports"
    Get-ChildItem -LiteralPath $reportsDir -Filter "research_candidates_*.md" |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First $Top Name, LastWriteTime, Length |
        Format-Table -AutoSize
}

function Show-ObsidianTree {
    $root = "G:\Program Files (x86)\Obsidian_base\中国A股荐股"
    if (-not (Test-Path -LiteralPath $root)) {
        Write-Host "Obsidian export root not found: $root"
        return
    }

    Write-Section "Root"
    Get-ChildItem -LiteralPath $root -Force |
        Select-Object Name, LastWriteTime |
        Format-Table -AutoSize

    $reviewRoot = Join-Path $root "每日复盘"
    if (Test-Path -LiteralPath $reviewRoot) {
        Write-Section "每日复盘"
        Get-ChildItem -LiteralPath $reviewRoot -Force |
            Sort-Object Name -Descending |
            Select-Object -First $Top Name, LastWriteTime |
            Format-Table -AutoSize
    }

    $planRoot = Join-Path $root "开盘计划"
    if (Test-Path -LiteralPath $planRoot) {
        Write-Section "开盘计划"
        Get-ChildItem -LiteralPath $planRoot -Force |
            Sort-Object Name -Descending |
            Select-Object -First $Top Name, LastWriteTime, Length |
            Format-Table -AutoSize
    }
}

function Invoke-DailyResearch {
    $script = Join-Path $PSScriptRoot "run_daily_research.ps1"
    & $script -TargetDate $TargetDate -PlanDate $PlanDate -NoObsidianExport:$NoObsidianExport -Force:$Force
}

function Invoke-NightlyPrep {
    $script = Join-Path $PSScriptRoot "run_nightly_research_prep.ps1"
    & $script -TargetDate $TargetDate -Force:$Force
}

switch ($Command) {
    "help" { Show-Help }
    "task-status" { Show-TaskStatus }
    "latest-ops" { Show-LatestOps }
    "obsidian-tree" { Show-ObsidianTree }
    "daily" { Invoke-DailyResearch }
    "nightly" { Invoke-NightlyPrep }
    "warehouse-status" { Invoke-Quant @("warehouse-status") }
    "data-loop" {
        $commandArgs = @("data-loop-status")
        if ($TargetDate) {
            $commandArgs += @("--target-date", $TargetDate)
        }
        if ($PlanDate) {
            $commandArgs += @("--plan-date", $PlanDate)
        }
        Invoke-Quant $commandArgs
    }
    "retention-plan" { Invoke-Quant @("data-retention-plan", "--top", $Top.ToString()) }
    "cache-status" {
        $commandArgs = @("cache-date-status", "--universe-file", "data/universe/a_stock.csv", "--show-stale", "--top", $Top.ToString())
        if ($TargetDate) {
            $commandArgs += @("--target-date", $TargetDate, "--exact-target-date")
        }
        Invoke-Quant $commandArgs
    }
    "track-candidates" {
        $commandArgs = @("track-candidates", "--top", $Top.ToString())
        if ($TargetDate) {
            $commandArgs += @("--until", $TargetDate)
        }
        Invoke-Quant $commandArgs
    }
}
