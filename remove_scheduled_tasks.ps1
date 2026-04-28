param(
    [string]$TaskPrefix = "UPValuation"
)

$ErrorActionPreference = "Continue"

$dailyTaskName = "$TaskPrefix-Daily"
$epsTaskName = "$TaskPrefix-EPS-Monthly"
$assumptionsTaskName = "$TaskPrefix-Assumptions-Monthly"

schtasks /Delete /F /TN $dailyTaskName | Out-Null
if ($LASTEXITCODE -eq 0) {
    Write-Host "[OK] Removed task: $dailyTaskName"
} else {
    Write-Host "[Skip] Task not found or not removed: $dailyTaskName"
}

schtasks /Delete /F /TN $epsTaskName | Out-Null
if ($LASTEXITCODE -eq 0) {
    Write-Host "[OK] Removed task: $epsTaskName"
} else {
    Write-Host "[Skip] Task not found or not removed: $epsTaskName"
}

schtasks /Delete /F /TN $assumptionsTaskName | Out-Null
if ($LASTEXITCODE -eq 0) {
    Write-Host "[OK] Removed task: $assumptionsTaskName"
} else {
    Write-Host "[Skip] Task not found or not removed: $assumptionsTaskName"
}
