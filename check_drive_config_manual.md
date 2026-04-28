# Google Drive 설정 검증 도구

## 📋 설정 검증 스크립트

다음 PowerShell 스크립트를 실행하여 설정이 제대로 되었는지 확인합니다.

### 사용 방법

```powershell
Set-Location "d:\00.개발\02.up_valuation"
. .\check_drive_config.ps1
```

또는 직접 실행:

```powershell
powershell -ExecutionPolicy Bypass -File "d:\00.개발\02.up_valuation\check_drive_config.ps1"
```

---

## ✅ 확인 항목

| 항목 | 확인 내용 |
|------|---------|
| 설정 파일 | `up_valuation_config.json` 존재 및 JSON 형식 유효 |
| Python 경로 | `pythonPath`에 지정된 Python 실행 파일 존재 |
| 업로드 활성화 | `enableGoogleDriveUpload` 값 확인 |
| JSON 키 파일 | `googleServiceAccountJsonPath` 지정 파일 존재 |
| JSON 키 형식 | 다운로드한 JSON 파일이 유효한 서비스 계정 형식 |
| 폴더 ID | `googleDriveFolderId` 값 입력 여부 |
| Python 권한 | Drive API 필수 라이브러리 설치 여부 |

---

## 🔧 수동 검증 (PowerShell)

### 1) 설정 파일 로드 및 확인

```powershell
$configPath = "d:\00.개발\02.up_valuation\up_valuation_config.json"
$config = Get-Content $configPath | ConvertFrom-Json

Write-Host "=== UP Valuation Google Drive 설정 ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "enableGoogleDriveUpload: $($config.enableGoogleDriveUpload)" -ForegroundColor Yellow
Write-Host "googleDriveFolderId: $($config.googleDriveFolderId)" -ForegroundColor Yellow
Write-Host "googleServiceAccountJsonPath: $($config.googleServiceAccountJsonPath)" -ForegroundColor Yellow
```

### 2) JSON 키 파일 검증

```powershell
$jsonPath = $config.googleServiceAccountJsonPath
if (Test-Path $jsonPath) {
    $serviceAccount = Get-Content $jsonPath | ConvertFrom-Json
    Write-Host "✓ JSON 파일 존재" -ForegroundColor Green
    Write-Host "  프로젝트 ID: $($serviceAccount.project_id)"
    Write-Host "  서비스 계정: $($serviceAccount.client_email)"
} else {
    Write-Host "✗ JSON 파일 없음: $jsonPath" -ForegroundColor Red
}
```

### 3) Python 라이브러리 확인

```powershell
$pythonExe = $config.pythonPath
& $pythonExe -c "import google.auth; import google.api_core; print('✓ Google API 라이브러리 설치됨')" 2>&1
```

### 4) 테스트 실행 (제한된 데이터)

```powershell
Set-Location "d:\00.개발\02.up_valuation"
./run_daily.ps1 --limit 5 --period 3mo --verbose
```

실행 후 로그에서 `[Drive]` 관련 메시지 확인:
- `[Drive] Completed: X file(s) created, Y file(s) updated` → 성공
- `[Drive] Error: ...` → 오류 (메시지 확인)
- `[Info] Google Drive upload skipped` → 설정 미활성화

---

## 🆘 문제 해결

### 오류: "Permission denied"

**원인:** Google Drive API 미활성화 또는 서비스 계정 권한 없음

**해결:**
1. Google Cloud Console에서 Drive API 활성화 확인 (Step 2)
2. Google Drive 폴더에서 서비스 계정 이메일 공유 확인 (Step 5.2)
   - 역할: **편집자 (Editor)** 이상

### 오류: "File not found"

**원인:** JSON 파일 경로 오류

**해결:**
```powershell
# 실제 파일 경로 확인
Get-Item "d:\00.개발\02.up_valuation\keys\*.json"

# 파일 목록 출력
ls "d:\00.개발\02.up_valuation\keys\"
```

### 오류: "Invalid JSON"

**원인:** JSON 파일이 손상되었거나 형식 오류

**해결:**
1. Google Cloud Console에서 새로운 JSON 키 발급
2. 기존 파일 삭제 후 새 파일로 교체

### 파일 업로드 안 됨

**체크리스트:**
```powershell
# 1. 설정 파일 확인
cat "d:\00.개발\02.up_valuation\up_valuation_config.json"

# 2. enableGoogleDriveUpload가 true인지 확인
# 3. 경로에 오류(따옴표, 기호)가 없는지 확인
# 4. JSON 파일 권한 확인 (읽기 가능)
Test-Path "d:\00.개발\02.up_valuation\keys\service_account.json" -PathType Leaf

# 5. 폴더 ID가 입력되었는지 확인 (빈 문자열 아님)
if ([string]::IsNullOrWhiteSpace($config.googleDriveFolderId)) {
    Write-Host "✗ 폴더 ID가 비어있습니다" -ForegroundColor Red
} else {
    Write-Host "✓ 폴더 ID: $($config.googleDriveFolderId)" -ForegroundColor Green
}
```

---

## 📝 설정 체크리스트

설정 전에 다음을 확인하세요:

- [ ] Google 계정 준비 완료
- [ ] Google Cloud 프로젝트 생성 완료
- [ ] Drive API 활성화 완료
- [ ] 서비스 계정 생성 완료
- [ ] JSON 키 파일 다운로드 완료
- [ ] JSON 파일을 `d:\00.개발\02.up_valuation\keys\` 에 저장 완료
- [ ] Google Drive 폴더 생성 완료
- [ ] 서비스 계정과 폴더 공유 완료 (편집자 권한)
- [ ] 폴더 ID 확인 및 복사 완료
- [ ] `up_valuation_config.json` 수정 완료
- [ ] 파일 저장 완료
- [ ] 테스트 실행 완료 및 성공 확인 완료

---

## 🎯 다음 단계

모든 설정이 완료되었다면:

1. **일일 자동 실행 확인**
   ```powershell
   # Windows Task Scheduler에서 스케줄 확인
   Get-ScheduledTask -TaskName "*up_valuation*" -ErrorAction SilentlyContinue | Format-Table TaskName, State
   ```

2. **수동 테스트**
   ```powershell
   Set-Location "d:\00.개발\02.up_valuation"
   ./run_daily.ps1 --limit 10
   ```

3. **Google Drive 확인**
   - https://drive.google.com 에서 업로드된 파일 확인

4. **핸드폰 확인**
   - Google Drive 앱에서 폴더 확인

---

**질문이 있으면 이 문서의 트러블슈팅 섹션을 참고하세요!**

