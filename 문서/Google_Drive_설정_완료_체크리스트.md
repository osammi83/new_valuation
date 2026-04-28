# 🚀 Google Drive 자동 업로드 - 설정 완료 가이드

> 현재 상태: **모든 준비 완료** ✅  
> 다음 단계: **Google Cloud 설정 3단계 → 테스트 실행 → 확인**

---

## 📋 체크리스트

이 문서를 따라 완료하면서 각 항목에 ☑️를 표시하세요.

### Phase 1️⃣: Google Cloud 설정 (외부)

Google Cloud Console에서 수행할 작업입니다.  
**소요 시간: 약 10-15분**

#### 단계별 가이드
- 📄 [Google_Drive_설정_가이드.md](Google_Drive_설정_가이드.md) **← 꼭 읽고 따라하세요!**

#### 진행 상황
- ☐ **Step 1:** Google Cloud Project 생성
- ☐ **Step 2:** Google Drive API 활성화  
- ☐ **Step 3:** 서비스 계정 생성
- ☐ **Step 4:** JSON 키 생성 및 저장
  - 저장 경로: `d:\00.개발\02.up_valuation\keys\service_account.json`
- ☐ **Step 5:** Google Drive 폴더 생성 및 공유
  - 폴더명: `UP_Valuation_Reports` (또는 원하는 이름)
  - 공유 대상: 서비스 계정 이메일 (편집자 권한)
  - 폴더 ID 복사: `googleDriveFolderId`로 사용할 값

---

### Phase 2️⃣: UP Valuation 설정 (로컬)

### A. 설정 파일 수정

✅ **파일:** `d:\00.개발\02.up_valuation\up_valuation_config.json`

```json
{
  "pythonPath": "d:/00.개발/.venv/Scripts/python.exe",
  "enableGoogleDriveUpload": true,
  "googleDriveFolderId": "[Step 5에서 복사한 폴더ID]",
  "googleServiceAccountJsonPath": "d:/00.개발/02.up_valuation/keys/service_account.json"
}
```

**예시 (실제 값으로 채우기):**
```json
{
  "pythonPath": "d:/00.개발/.venv/Scripts/python.exe",
  "enableGoogleDriveUpload": true,
  "googleDriveFolderId": "1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p",
  "googleServiceAccountJsonPath": "d:/00.개발/02.up_valuation/keys/service_account.json"
}
```

- ☐ VS Code에서 파일 열기
- ☐ 값 수정
- ☐ `Ctrl+S` 저장
- ☐ 따옴표, 경로 등 형식 확인 (JSON 형식 오류 없는지)

### B. 자동 검증 실행

PowerShell을 열고 다음 명령 실행:

```powershell
Set-Location "d:\00.개발\02.up_valuation"
./check_drive_config.ps1
```

결과 해석:
- ✅ **"✅ 설정 검증 성공!"** → Phase 3로 진행
- ⚠️ **"⚠️ 설정 검증 성공 (업로드 비활성화됨)"** → `enableGoogleDriveUpload = true`로 수정
- ❌ **"❌ 설정 검증 실패"** → 오류 메시지 확인 후 수정

- ☐ 검증 실행 완료
- ☐ 모든 체크항목 통과 확인

---

### Phase 3️⃣: 테스트 실행 (검증)

### A. 테스트 파이프라인 실행

PowerShell에서:

```powershell
Set-Location "d:\00.개발\02.up_valuation"
./run_daily.ps1 --limit 10 --period 6mo
```

실행 중 다음을 확인:
- 터미널에서 리포트 생성 진행 상황 표시
- 약 2-3분 대기
- 완료 후 로그 확인

### B. 로그 확인

실행 완료 후 터미널에서 다음 메시지 찾기:

#### ✅ 성공 메시지
```
[Drive] Completed: X file(s) created, Y file(s) updated
```

#### ❌ 오류 메시지 (수정 필요)
```
[Drive] Error: ...
```
→ 오류 메시지 확인하고 위의 트러블슈팅 참고

#### ⚠️ 스킵 메시지 (설정 미활성화)
```
[Info] Google Drive upload skipped...
```
→ `enableGoogleDriveUpload = true` 확인

- ☐ 테스트 실행 완료
- ☐ `[Drive]` 관련 메시지 확인
- ☐ 오류/스킵 메시지 해결

### C. Google Drive 확인

#### 웹 브라우저에서:
1. https://drive.google.com 열기
2. `UP_Valuation_Reports` 폴더 열기
3. 다음 파일들 업로드 확인:
  - `상세리포트_2026-04-24.csv` (또는 오늘 날짜)
  - `종목선정_핵심근거_2026-04-24.csv`
  - `최종매수_30일타임라인_2026-04-24.csv`
  - `최종매수_전일비교_2026-04-24_vs_2026-04-23.csv`
   - 기타 `_2026-04-24.csv` 파일들

- ☐ Google Drive 폴더 확인
- ☐ 생성된 CSV 파일 확인

---

### Phase 4️⃣: 핸드폰 확인 (선택)

> 이 단계는 선택 사항입니다. 노트북에서만 실행하고 싶으면 생략 가능.

### A. Google Drive 앱 설치

- **iPhone:** App Store → "Google Drive" 검색 → 설치
- **Android:** Google Play → "Google Drive" 검색 → 설치

### B. 폴더 접근

1. Google Drive 앱 열기
2. Google 계정으로 로그인
3. 폴더 목록에서 `UP_Valuation_Reports` 찾기
4. 폴더 탭 → CSV 파일들 확인

### C. 파일 보기 옵션

**옵션 1: 웹 프리뷰 (추천)**
- CSV 파일 탭 → "Google Sheets로 열기"
- 브라우저에서 미리보기

**옵션 2: 다운로드 후 보기**
- CSV 파일 우클릭 → 다운로드
- Excel 또는 Numbers에서 열기

- ☐ Google Drive 앱 설치
- ☐ 폴더 접근 확인
- ☐ 파일 보기 확인

---

## ⚡ 최종 단계: 자동 스케줄러 설정 (이미 됨)

Windows Task Scheduler에 다음 설정이 이미 등록되어 있습니다:

| 항목 | 값 |
|------|-----|
| 작업명 | `up_valuation_daily_report` |
| 실행 주기 | 매일 08:30 |
| 실행 명령 | `d:\00.개발\02.up_valuation\run_daily.ps1` |
| 파일 업로드 | Google Drive (자동) |

**확인 방법:**
```powershell
Get-ScheduledTask -TaskName "*up_valuation*" | Select-Object TaskName, State, LastRunTime, NextRunTime | Format-Table -AutoSize
```

---

## 🆘 문제 해결

### Q1: "[Drive] Error: Permission denied" 나옴

**A: Google Drive API 권한 문제**
- ✅ Google Cloud Console에서 Drive API 활성화 재확인
- ✅ Google Drive 폴더를 서비스 계정과 공유했는지 확인
  - 폴더 우클릭 → 공유 → 서비스 계정 이메일 확인
  - 역할: **편집자 (Editor)** 이상

### Q2: "[Drive] Error: Folder not found" 나옴

**A: 폴더 ID 오류**
- ✅ Google Drive에서 폴더 열기
- ✅ 주소창의 URL 확인: `https://drive.google.com/drive/folders/[FOLDER_ID]`
- ✅ `[FOLDER_ID]` 부분만 복사 (약 33자)
- ✅ `up_valuation_config.json`의 `googleDriveFolderId`에 다시 입력
- ✅ 저장 후 테스트 재실행

### Q3: "[Drive] Error: File not found" (JSON 키)

**A: JSON 파일 경로 오류**
- ✅ `d:\00.개발\02.up_valuation\keys\` 폴더에 파일 있는지 확인
- ✅ 파일명 확인 (경로와 정확히 같은지)
- ✅ `up_valuation_config.json`의 경로 재확인 (따옴표 없음)

### Q4: 파일이 업로드되지 않음

**A: 설정 미활성화 또는 미저장**
- ✅ `enableGoogleDriveUpload` = `true`인지 확인
- ✅ 파일 저장 여부 확인 (Ctrl+S)
- ✅ PowerShell 재실행
- ✅ `./check_drive_config.ps1` 다시 실행해서 모든 항목 통과 확인

### Q5: 핸드폰에서 파일이 안 보임

**A: 공유 또는 동기화 문제**
- ✅ Google Drive 앱 새로고침 (아래로 스와이프)
- ✅ 노트북에서 https://drive.google.com 열어서 파일 있는지 확인
- ✅ Google Cloud 콘솔에서 폴더 공유 재확인

---

## 📊 상태 확인 명령어

### 1️⃣ 설정 파일 내용 보기
```powershell
Get-Content "d:\00.개발\02.up_valuation\up_valuation_config.json" | ConvertFrom-Json | Format-Table
```

### 2️⃣ JSON 키 파일 확인
```powershell
$json = Get-Content "d:\00.개발\02.up_valuation\keys\service_account.json" | ConvertFrom-Json
$json | Select-Object project_id, client_email, type | Format-Table
```

### 3️⃣ 스케줄 확인
```powershell
Get-ScheduledTask -TaskName "*up_valuation*" | Format-List TaskName, State, LastRunTime, NextRunTime
```

### 4️⃣ 최근 실행 로그 보기
```powershell
Get-EventLog -LogName "System" -Source "Task Scheduler" -Newest 10 | Format-Table TimeGenerated, Message
```

---

## ✅ 모든 설정 완료!

설정이 완료되면:

✨ **매일 08:30에 자동으로:**
1. UP Valuation 리포트 생성
2. 모든 CSV 파일 생성
3. Google Drive에 자동 업로드
4. 핸드폰에서 확인 가능

🎯 **다음부터는:**
- 노트북: 자동 실행 (별도 작업 없음)
- 핸드폰: Google Drive 앱에서 확인
- 긴급 수동 실행: `./run_daily.ps1 --limit 30`

---

## 📚 참고 문서

| 문서 | 용도 |
|------|------|
| [Google_Drive_설정_가이드.md](Google_Drive_설정_가이드.md) | Google Cloud 설정 (필수) |
| [check_drive_config_manual.md](check_drive_config_manual.md) | 수동 검증 방법 |
| [자동화_운영_매뉴얼.md](자동화_운영_매뉴얼.md) | 전체 자동화 가이드 |

---

**궁금한 점이 있으면 위의 트러블슈팅 섹션을 참고하세요!** 🚀

