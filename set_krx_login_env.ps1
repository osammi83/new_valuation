param(
    [ValidateSet('User', 'Machine')]
    [string]$Scope = 'User'
)

$ErrorActionPreference = 'Stop'

Write-Host ""
Write-Host "[KRX] Set KRX_ID / KRX_PW environment variables" -ForegroundColor Cyan
Write-Host "- Scope: $Scope" -ForegroundColor Cyan
Write-Host "- These are KRX login credentials (ID/PW), not API key." -ForegroundColor Cyan
Write-Host "- This script will NOT write credentials to project files." -ForegroundColor Cyan
Write-Host ""

$krxId = Read-Host -Prompt 'KRX ID 입력'
if([string]::IsNullOrWhiteSpace($krxId)){
    throw 'Empty KRX ID. Aborted.'
}

$krxPwSecure = Read-Host -Prompt 'KRX Password 입력' -AsSecureString
if($krxPwSecure.Length -eq 0){
    throw 'Empty KRX password. Aborted.'
}

$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($krxPwSecure)
try {
    $krxPw = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
}

# Set for current PowerShell session (immediate use)
$env:KRX_ID = $krxId
$env:KRX_PW = $krxPw

# Persist to Windows environment variables
if($Scope -eq 'Machine'){
    Write-Host '[Warn] Machine scope may require Administrator privileges.' -ForegroundColor Yellow
    [Environment]::SetEnvironmentVariable('KRX_ID', $krxId, 'Machine')
    [Environment]::SetEnvironmentVariable('KRX_PW', $krxPw, 'Machine')
} else {
    [Environment]::SetEnvironmentVariable('KRX_ID', $krxId, 'User')
    [Environment]::SetEnvironmentVariable('KRX_PW', $krxPw, 'User')
}

Write-Host "[OK] KRX_ID/KRX_PW are set for current session and persisted ($Scope)." -ForegroundColor Green
Write-Host ""
Write-Host "To verify in THIS PowerShell window:" -ForegroundColor Gray
Write-Host "  echo $env:KRX_ID" -ForegroundColor Gray
Write-Host "  echo $env:KRX_PW" -ForegroundColor Gray
Write-Host ""
Write-Host "To verify in a NEW PowerShell window (after reopening):" -ForegroundColor Gray
Write-Host "  [Environment]::GetEnvironmentVariable('KRX_ID','User')" -ForegroundColor Gray
Write-Host "  [Environment]::GetEnvironmentVariable('KRX_PW','User')" -ForegroundColor Gray
