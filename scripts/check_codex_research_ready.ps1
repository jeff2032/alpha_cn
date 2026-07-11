param(
    [string]$AlphaRoot = "G:\OwnProject\alpha_cn",
    [string]$ObsidianRoot = "G:\Program Files (x86)\Obsidian_base"
)

$ErrorActionPreference = "Continue"
$rows = @()

$nightly = Get-ScheduledTask -TaskName "AlphaCN Nightly Prep" -ErrorAction SilentlyContinue
$rows += [pscustomobject]@{
    Component = "AlphaCN Nightly Prep"
    Status = if ($nightly) { $nightly.State } else { "MISSING" }
    Detail = "Daily 16:30 data and research preparation"
}

$contextRoot = Join-Path $AlphaRoot "data\context\research"
$latestContext = Get-ChildItem -Recurse $contextRoot -Filter *.json -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
$rows += [pscustomobject]@{
    Component = "Research Context Pack"
    Status = if ($latestContext) { "READY" } else { "MISSING" }
    Detail = if ($latestContext) { $latestContext.FullName } else { "No Context Pack" }
}

$warehouse = Join-Path $AlphaRoot "data\warehouse\alpha_cn.duckdb"
$rows += [pscustomobject]@{
    Component = "Research warehouse"
    Status = if (Test-Path -LiteralPath $warehouse) { "READY" } else { "MISSING" }
    Detail = $warehouse
}

$skill = Join-Path $env:USERPROFILE ".codex\skills\investment-research"
$rows += [pscustomobject]@{
    Component = "AI Berkshire skills"
    Status = if (Test-Path -LiteralPath $skill) { "READY" } else { "MISSING" }
    Detail = $skill
}

$rows += [pscustomobject]@{
    Component = "Obsidian conclusion layer"
    Status = if (Test-Path -LiteralPath $ObsidianRoot) { "READY" } else { "MISSING" }
    Detail = $ObsidianRoot
}

$rows | Format-Table -AutoSize
if ($rows.Status -contains "MISSING") {
    exit 1
}
