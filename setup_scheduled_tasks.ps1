param(
    [string]$DailyTime = "08:30",
    [string]$MonthlyTime = "08:00",
    [string]$AssumptionsMonthlyTime = "08:10",
    [string]$TaskPrefix = "UPValuation"
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$runDailyPath = Join-Path $scriptDir "run_daily.ps1"
$runEpsPath = Join-Path $scriptDir "run_eps_cache_refresh.ps1"
$runAssumptionsPath = Join-Path $scriptDir "run_assumptions_refresh.ps1"

if (-not (Test-Path $runDailyPath)) {
    throw "Missing file: $runDailyPath"
}
if (-not (Test-Path $runEpsPath)) {
    throw "Missing file: $runEpsPath"
}
if (-not (Test-Path $runAssumptionsPath)) {
    throw "Missing file: $runAssumptionsPath"
}

$dailyTaskName = "$TaskPrefix-Daily"
$epsTaskName = "$TaskPrefix-EPS-Monthly"
$assumptionsTaskName = "$TaskPrefix-Assumptions-Monthly"

function Invoke-Schtasks {
    param([string[]]$Args)
    & schtasks @Args
    if ($LASTEXITCODE -ne 0) {
        throw "schtasks failed with exit code $LASTEXITCODE"
    }
}

$dailyCommand = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$runDailyPath`""
$epsCommand = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$runEpsPath`""
$assumptionsCommand = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$runAssumptionsPath`""

# Daily report task
Invoke-Schtasks @('/Create', '/F', '/SC', 'DAILY', '/ST', $DailyTime, '/TN', $dailyTaskName, '/TR', $dailyCommand)

# EPS refresh task monthly (cache script itself skips if cache is still fresh)
Invoke-Schtasks @('/Create', '/F', '/SC', 'MONTHLY', '/MO', '1', '/D', '1', '/ST', $MonthlyTime, '/TN', $epsTaskName, '/TR', $epsCommand)

# assumptions.csv refresh task monthly
Invoke-Schtasks @('/Create', '/F', '/SC', 'MONTHLY', '/MO', '1', '/D', '1', '/ST', $AssumptionsMonthlyTime, '/TN', $assumptionsTaskName, '/TR', $assumptionsCommand)

Write-Host "[OK] Scheduled tasks created/updated"
Write-Host "  - $dailyTaskName : DAILY at $DailyTime"
Write-Host "  - $epsTaskName   : MONTHLY on day 1 at $MonthlyTime"
Write-Host "  - $assumptionsTaskName : MONTHLY on day 1 at $AssumptionsMonthlyTime"

Write-Host ""
Write-Host "[Query]"
Invoke-Schtasks @('/Query', '/TN', $dailyTaskName, '/V', '/FO', 'LIST')
Write-Host ""
Invoke-Schtasks @('/Query', '/TN', $epsTaskName, '/V', '/FO', 'LIST')
Write-Host ""
Invoke-Schtasks @('/Query', '/TN', $assumptionsTaskName, '/V', '/FO', 'LIST')
