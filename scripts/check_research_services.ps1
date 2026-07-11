param(
    [string]$AlphaRoot = "G:\OwnProject\alpha_cn",
    [string]$DsaRoot = "G:\OwnProject\daily_stock_analysis",
    [string]$BerkshireRoot = "G:\OwnProject\ai-berkshire",
    [string]$DsaBaseUrl = "http://127.0.0.1:8000"
)

$ErrorActionPreference = "Continue"
$rows = @()

$nightly = Get-ScheduledTask -TaskName "AlphaCN Nightly Prep" -ErrorAction SilentlyContinue
$rows += [pscustomobject]@{
    Component = "AlphaCN Nightly Prep"
    Status = if ($nightly) { $nightly.State } else { "MISSING" }
    Detail = "16:30 market data and research preparation"
}

$dsaTask = Get-ScheduledTask -TaskName "AlphaCN Daily Stock Analysis" -ErrorAction SilentlyContinue
$rows += [pscustomobject]@{
    Component = "DSA startup task"
    Status = if ($dsaTask) { $dsaTask.State } else { "MISSING" }
    Detail = "start at user logon"
}

try {
    $health = Invoke-WebRequest -UseBasicParsing -Uri "$DsaBaseUrl/api/health" -TimeoutSec 5
    $dsaStatus = if ($health.StatusCode -eq 200) { "OK" } else { "HTTP $($health.StatusCode)" }
} catch {
    $dsaStatus = "OFFLINE"
}
$rows += [pscustomobject]@{
    Component = "Daily Stock Analysis"
    Status = $dsaStatus
    Detail = $DsaBaseUrl
}

$latestContext = Get-ChildItem -Recurse (Join-Path $AlphaRoot "data\context\research") -Filter *.json -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
$rows += [pscustomobject]@{
    Component = "AlphaCN Context Pack"
    Status = if ($latestContext) { "OK" } else { "MISSING" }
    Detail = if ($latestContext) { $latestContext.FullName } else { "No context pack" }
}

$berkshireSkill = Join-Path $env:USERPROFILE ".codex\skills\investment-research"
$rows += [pscustomobject]@{
    Component = "AI Berkshire skills"
    Status = if ((Test-Path $BerkshireRoot) -and (Test-Path $berkshireSkill)) { "READY" } else { "MISSING" }
    Detail = $berkshireSkill
}

try {
    $setup = Invoke-RestMethod -Uri "$DsaBaseUrl/api/v1/system/config/setup/status" -TimeoutSec 5
    $primary = $setup.checks | Where-Object { $_.key -eq "llm_primary" } | Select-Object -First 1
    $modelStatus = if ($primary.status -eq "configured") { "READY" } else { "SETUP_REQUIRED" }
    $modelDetail = if ($primary.status -eq "configured") { "Primary model configured" } else { "Open DSA Settings and configure the primary LLM" }
} catch {
    $modelStatus = "UNKNOWN"
    $modelDetail = "Unable to read DSA setup status"
}
$rows += [pscustomobject]@{
    Component = "DSA model configuration"
    Status = $modelStatus
    Detail = $modelDetail
}

$rows | Format-Table -AutoSize
if ($rows.Status -contains "MISSING" -or $rows.Status -contains "OFFLINE") {
    exit 1
}
