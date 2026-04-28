param(
    [ValidateSet('User', 'Machine')]
    [string]$Scope = 'User'
)

$ErrorActionPreference = 'Stop'

Write-Host ""
Write-Host "[DART] Set DART_API_KEY environment variable" -ForegroundColor Cyan
Write-Host "- Scope: $Scope" -ForegroundColor Cyan
Write-Host "- This script will NOT write your key to any project file." -ForegroundColor Cyan
Write-Host ""

$key = Read-Host -Prompt 'Paste your DART API key'
if([string]::IsNullOrWhiteSpace($key)){
    throw 'Empty key. Aborted.'
}

# Set for current PowerShell session (immediate use)
$env:DART_API_KEY = $key

# Persist to Windows environment variables
if($Scope -eq 'Machine'){
    Write-Host '[Warn] Machine scope may require Administrator privileges.' -ForegroundColor Yellow
    [Environment]::SetEnvironmentVariable('DART_API_KEY', $key, 'Machine')
} else {
    [Environment]::SetEnvironmentVariable('DART_API_KEY', $key, 'User')
}

Write-Host "[OK] DART_API_KEY is set for the current session and persisted ($Scope)." -ForegroundColor Green
Write-Host ""
Write-Host "To verify in THIS PowerShell window:" -ForegroundColor Gray
Write-Host "  echo $env:DART_API_KEY" -ForegroundColor Gray
Write-Host ""
Write-Host "To verify in a NEW PowerShell window (after reopening):" -ForegroundColor Gray
Write-Host "  [Environment]::GetEnvironmentVariable('DART_API_KEY','User')" -ForegroundColor Gray
