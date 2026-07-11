param(
    [string]$TaskName = "AlphaCN Daily Stock Analysis",
    [string]$ProjectRoot = "G:\OwnProject\alpha_cn"
)

$ErrorActionPreference = "Stop"
$launcher = Join-Path $ProjectRoot "scripts\start_daily_stock_analysis.ps1"
if (-not (Test-Path $launcher)) {
    throw "Launcher is missing: $launcher"
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$launcher`"" `
    -WorkingDirectory $ProjectRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$trigger.Delay = "PT30S"
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Start the Daily Stock Analysis web/API service for the AlphaCN research workflow." `
    -Force | Out-Null

Write-Output "Registered task: $TaskName"
