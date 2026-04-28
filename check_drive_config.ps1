#!/usr/bin/env powershell
# UP Valuation Google Drive 설정 검증 도구
# 
# 사용법:
#   ./check_drive_config.ps1
#   powershell -ExecutionPolicy Bypass -File "./check_drive_config.ps1"

$ErrorActionPreference = "SilentlyContinue"

# ============================
# 색상 및 심볼 정의
# ============================
$OK = "✓"
$FAIL = "✗"
$WARN = "⚠"
$INFO = "ℹ"

function Write-Success {
    param([string]$Message)
    Write-Host "$OK $Message" -ForegroundColor Green
}

function Write-Error {
    param([string]$Message)
    Write-Host "$FAIL $Message" -ForegroundColor Red
}

function Write-Warning {
    param([string]$Message)
    Write-Host "$WARN $Message" -ForegroundColor Yellow
}

function Write-Info {
    param([string]$Message)
    Write-Host "$INFO $Message" -ForegroundColor Cyan
}

# ============================
# 체크 결과 카운터
# ============================
$passCount = 0
$failCount = 0
$warnCount = 0

# ============================
# 시작
# ============================
Write-Host ""
Write-Host "========================================" -ForegroundColor Magenta
Write-Host "  UP Valuation Google Drive 설정 검증" -ForegroundColor Magenta
Write-Host "========================================" -ForegroundColor Magenta
Write-Host ""

# ============================
# 1. 설정 파일 존재 여부
# ============================
Write-Host "1️⃣ 설정 파일 검증" -ForegroundColor Cyan
Write-Host "─────────────────────────────" -ForegroundColor DarkGray

$configPath = "d:\00.개발\02.up_valuation\up_valuation_config.json"
if (Test-Path $configPath) {
    Write-Success "설정 파일 존재: $configPath"
    $passCount++
} else {
    Write-Error "설정 파일 없음: $configPath"
    $failCount++
    Write-Host ""
    Write-Host "다음 문서를 참고하여 설정 파일을 생성해주세요:" -ForegroundColor Yellow
    Write-Host "  📄 Google_Drive_설정_가이드.md - Step 6" -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

# ============================
# 2. JSON 파일 형식 검증
# ============================
Write-Host ""
Write-Host "2️⃣ JSON 형식 검증" -ForegroundColor Cyan
Write-Host "─────────────────────────────" -ForegroundColor DarkGray

try {
    $config = Get-Content $configPath | ConvertFrom-Json
    Write-Success "JSON 형식 유효"
    $passCount++
} catch {
    Write-Error "JSON 형식 오류: $_"
    $failCount++
    exit 1
}

# ============================
# 3. 필수 설정값 확인
# ============================
Write-Host ""
Write-Host "3️⃣ 필수 설정값 확인" -ForegroundColor Cyan
Write-Host "─────────────────────────────" -ForegroundColor DarkGray

# 3.1 enableGoogleDriveUpload
if ($null -ne $config.enableGoogleDriveUpload) {
    if ($config.enableGoogleDriveUpload -eq $true) {
        Write-Success "enableGoogleDriveUpload = true (업로드 활성화됨)"
        $passCount++
    } else {
        Write-Warning "enableGoogleDriveUpload = false (업로드 비활성화됨)"
        $warnCount++
    }
} else {
    Write-Error "enableGoogleDriveUpload 미설정"
    $failCount++
}

# 3.2 googleDriveFolderId
if ([string]::IsNullOrWhiteSpace($config.googleDriveFolderId)) {
    Write-Error "googleDriveFolderId 빈 상태"
    Write-Info "Google Drive 폴더 URL에서 폴더ID를 복사하여 입력해주세요"
    Write-Info "예: 1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p"
    $failCount++
} else {
    Write-Success "googleDriveFolderId 설정됨"
    Write-Host "  값: $($config.googleDriveFolderId)" -ForegroundColor DarkGray
    $passCount++
}

# 3.3 googleServiceAccountJsonPath
if ([string]::IsNullOrWhiteSpace($config.googleServiceAccountJsonPath)) {
    Write-Error "googleServiceAccountJsonPath 빈 상태"
    $failCount++
} else {
    Write-Host "googleServiceAccountJsonPath 설정됨" -ForegroundColor Green
    Write-Host "  값: $($config.googleServiceAccountJsonPath)" -ForegroundColor DarkGray
    $passCount++
}

# ============================
# 4. Python 경로 검증
# ============================
Write-Host ""
Write-Host "4️⃣ Python 실행 파일 검증" -ForegroundColor Cyan
Write-Host "─────────────────────────────" -ForegroundColor DarkGray

$pythonPath = $config.pythonPath
if ([string]::IsNullOrWhiteSpace($pythonPath)) {
    Write-Error "pythonPath 설정값 없음"
    $failCount++
} elseif (Test-Path $pythonPath) {
    Write-Success "Python 실행 파일 존재: $pythonPath"
    $passCount++
} else {
    Write-Error "Python 실행 파일 없음: $pythonPath"
    $failCount++
}

# ============================
# 5. JSON 키 파일 검증
# ============================
Write-Host ""
Write-Host "5️⃣ JSON 키 파일 검증" -ForegroundColor Cyan
Write-Host "─────────────────────────────" -ForegroundColor DarkGray

$jsonKeyPath = $config.googleServiceAccountJsonPath
if (Test-Path $jsonKeyPath) {
    Write-Success "JSON 키 파일 존재: $jsonKeyPath"
    $passCount++
    
    try {
        $serviceAccount = Get-Content $jsonKeyPath | ConvertFrom-Json
        
        # 필수 필드 확인
        $requiredFields = @("type", "project_id", "private_key", "client_email", "client_id")
        $missingFields = @()
        
        foreach ($field in $requiredFields) {
            if ([string]::IsNullOrWhiteSpace($serviceAccount.$field)) {
                $missingFields += $field
            }
        }
        
        if ($missingFields.Count -eq 0) {
            Write-Success "JSON 키 파일 형식 유효"
            Write-Host "  프로젝트: $($serviceAccount.project_id)" -ForegroundColor DarkGray
            Write-Host "  서비스계정: $($serviceAccount.client_email)" -ForegroundColor DarkGray
            Write-Host "  타입: $($serviceAccount.type)" -ForegroundColor DarkGray
            $passCount++
        } else {
            Write-Error "JSON 키 파일 필드 누락: $($missingFields -join ', ')"
            $failCount++
        }
    } catch {
        Write-Error "JSON 키 파일 형식 오류: $_"
        $failCount++
    }
} else {
    Write-Error "JSON 키 파일 없음: $jsonKeyPath"
    Write-Info "Google Cloud Console에서 서비스 계정 JSON 키를 다운로드하세요"
    Write-Info "📄 Google_Drive_설정_가이드.md - Step 4 참고" -ForegroundColor Yellow
    $failCount++
}

# ============================
# 6. Python 라이브러리 확인
# ============================
Write-Host ""
Write-Host "6️⃣ Google API 라이브러리 확인" -ForegroundColor Cyan
Write-Host "─────────────────────────────" -ForegroundColor DarkGray

if ($pythonPath -and (Test-Path $pythonPath)) {
    try {
        $output = & $pythonPath -c "import google.auth; import google.oauth2.service_account; import google.api_client" 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Success "Google API 라이브러리 설치됨"
            $passCount++
        } else {
            Write-Warning "Google API 라이브러리 설치 필요"
            Write-Info "다음 명령 실행: pip install google-auth google-api-python-client"
            $warnCount++
        }
    } catch {
        Write-Warning "Google API 라이브러리 확인 불가: $_"
        $warnCount++
    }
} else {
    Write-Warning "Python 경로 오류로 라이브러리 확인 스킵"
    $warnCount++
}

# ============================
# 7. 폴더 ID 형식 검증
# ============================
Write-Host ""
Write-Host "7️⃣ 폴더 ID 형식 검증" -ForegroundColor Cyan
Write-Host "─────────────────────────────" -ForegroundColor DarkGray

if ($config.googleDriveFolderId -match "^[a-zA-Z0-9_-]{20,}$") {
    Write-Success "폴더 ID 형식 유효"
    Write-Host "  길이: $($config.googleDriveFolderId.Length)자" -ForegroundColor DarkGray
    $passCount++
} else {
    Write-Warning "폴더 ID 형식 의심스러움 (유효하지 않을 수 있음)"
    Write-Host "  값: $($config.googleDriveFolderId)" -ForegroundColor DarkGray
    Write-Info "Google Drive 폴더 URL의 /folders/ 뒤 부분을 정확히 복사했는지 확인"
    $warnCount++
}

# ============================
# 결과 요약
# ============================
Write-Host ""
Write-Host "========================================" -ForegroundColor Magenta
Write-Host "  검증 결과 요약" -ForegroundColor Magenta
Write-Host "========================================" -ForegroundColor Magenta
Write-Host ""

Write-Host "✓ 통과: $passCount" -ForegroundColor Green
Write-Host "✗ 실패: $failCount" -ForegroundColor Red
Write-Host "⚠ 경고: $warnCount" -ForegroundColor Yellow
Write-Host ""

# ============================
# 최종 판정
# ============================
if ($failCount -gt 0) {
    Write-Host "❌ 설정 검증 실패" -ForegroundColor Red
    Write-Host ""
    Write-Host "위의 실패 항목들을 확인하고 다음 문서를 참고하세요:" -ForegroundColor Yellow
    Write-Host "  📄 Google_Drive_설정_가이드.md" -ForegroundColor Yellow
    Write-Host "  📄 check_drive_config_manual.md" -ForegroundColor Yellow
    Write-Host ""
    exit 1
} elseif ($config.enableGoogleDriveUpload -eq $false) {
    Write-Host "⚠️ 설정 검증 성공 (업로드 비활성화됨)" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "설정을 모두 완료했다면, Google Drive 업로드를 활성화하세요:" -ForegroundColor Cyan
    Write-Host "  enableGoogleDriveUpload = true" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "설정 후 다시 이 스크립트를 실행해주세요." -ForegroundColor Cyan
    Write-Host ""
    exit 0
} else {
    Write-Host "✅ 설정 검증 성공!" -ForegroundColor Green
    Write-Host ""
    Write-Host "다음 단계: 테스트 실행" -ForegroundColor Cyan
    Write-Host "  ./run_daily.ps1 --limit 10" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "실행 후 다음을 확인하세요:" -ForegroundColor Cyan
    Write-Host "  1. 터미널에서 '[Drive] Completed' 메시지 확인" -ForegroundColor Cyan
    Write-Host "  2. Google Drive 폴더에서 업로드된 파일 확인" -ForegroundColor Cyan
    Write-Host ""
}
