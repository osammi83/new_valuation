# Google Drive 자동 업로드 설정 가이드

> 이 가이드를 따라 Google Cloud 서비스 계정을 생성하고 UP Valuation 파이프라인과 Google Drive를 연동합니다.

---

## 📋 필요한 것

- Google 계정 (Gmail 계정)
- Google Drive (무료 사용 가능)
- 약 10-15분

---

## 🔧 Step 1: Google Cloud Project 생성

### 1.1) Google Cloud Console 접속
- **URL:** https://console.cloud.google.com/
- 로그인 (Gmail 계정 사용)

### 1.2) 새 프로젝트 생성

| 단계 | 작업 |
|------|------|
| 화면 상단 | "프로젝트 선택" → "새 프로젝트" 클릭 |
| 프로젝트 이름 | 입력 예: `up-valuation-drive` |
| 조직 | 선택 안 함 (개인 계정이므로) |
| 만들기 | 클릭 후 몇 초 대기 |

### 1.3) 새 프로젝트 선택
- 우측 상단의 프로젝트 선택 드롭다운에서 `up-valuation-drive` 선택

---

## 🔑 Step 2: Drive API 활성화

### 2.1) API 검색
- 좌측 메뉴 → **APIs & Services** → **Library**
- 검색창에 `Google Drive API` 검색

### 2.2) API 활성화
- "Google Drive API" 선택
- **ENABLE** 버튼 클릭
- 몇 초 대기 (활성화 완료)

---

## 👤 Step 3: 서비스 계정 생성

### 3.1) 서비스 계정 페이지로 이동
- 좌측 메뉴 → **APIs & Services** → **Credentials**
- 화면 상단 **+ CREATE CREDENTIALS** → **Service Account** 선택

### 3.2) 서비스 계정 정보 입력

| 필드 | 입력값 |
|------|--------|
| Service account name | `up-valuation` |
| Service account ID | 자동 생성 (수정 불필요) |
| Description | `UP Valuation daily report uploader` |

- **CREATE AND CONTINUE** 클릭

### 3.3) 권한 부여 (선택 사항)
- "Grant this service account access to project" 섹션
- 입력 생략, **CONTINUE** 클릭

### 3.4) 사용자 권한 부여 (선택 사항)
- 입력 생략, **DONE** 클릭

---

## 🔐 Step 4: 서비스 계정 JSON 키 생성

### 4.1) 서비스 계정 선택
- **Credentials** 페이지에서 **Service Accounts** 섹션
- 방금 만든 `up-valuation` 계정 클릭

### 4.2) 키 생성
- **Keys** 탭 클릭
- **ADD KEY** → **Create new key** 선택
- **Key type:** JSON 선택
- **CREATE** 버튼 클릭
- **JSON 파일이 자동으로 다운로드됨**

### 4.3) 다운로드한 파일 저장
- 파일 이름: `[project-id]-[hash].json` (자동 생성)
- 저장 위치: **`d:\00.개발\02.up_valuation\keys\`** 폴더에 저장
  - 폴더가 없으면 먼저 생성
  - 파일명을 `service_account.json`으로 변경 (선택)

```powershell
# PowerShell에서 폴더 생성
New-Item -ItemType Directory -Force -Path "d:\00.개발\02.up_valuation\keys" | Out-Null
```

### 4.4) JSON 파일 확인
- 파일 내용에는 다음과 같이 포함됨:
  ```json
  {
    "type": "service_account",
    "project_id": "up-valuation-drive-xxxxx",
    "private_key_id": "...",
    "private_key": "-----BEGIN PRIVATE KEY-----\n...",
    "client_email": "up-valuation@up-valuation-drive-xxxxx.iam.gserviceaccount.com",
    "client_id": "...",
    ...
  }
  ```

---

## 📁 Step 5: Google Drive 폴더 생성 및 공유

### 5.1) 새 폴더 생성
- **Google Drive:** https://drive.google.com
- 좌측 메뉴 **새로 만들기** → **폴더**
- 폴더 이름: `UP_Valuation_Reports` (또는 원하는 이름)

### 5.2) 서비스 계정과 공유
- 방금 만든 폴더 우클릭 → **공유**
- 공유 대상 이메일: **`up-valuation@up-valuation-drive-xxxxx.iam.gserviceaccount.com`**
  - (Step 4.4의 `client_email` 복사)
- 역할: **편집자 (Editor)** 선택
- **공유** 클릭

### 5.3) 폴더 URL에서 folderId 확인
- Google Drive에서 폴더 열기
- 브라우저 주소창의 URL:
  ```
  https://drive.google.com/drive/folders/[FOLDER_ID]
  ```
- `[FOLDER_ID]` 부분 복사 (약 33자의 영숫자)
- 예: `1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p`

---

## ✅ Step 6: UP Valuation 설정 파일 수정

### 6.1) 설정 파일 열기
- **파일:** `d:\00.개발\02.up_valuation\up_valuation_config.json`
- VS Code에서 열기

### 6.2) 설정 입력

다음과 같이 수정:

```json
{
  "pythonPath": "d:/00.개발/.venv/Scripts/python.exe",
  "enableGoogleDriveUpload": true,
  "googleDriveFolderId": "[위에서복사한폴더ID]",
  "googleServiceAccountJsonPath": "d:/00.개발/02.up_valuation/keys/service_account.json"
}
```

**예시:**
```json
{
  "pythonPath": "d:/00.개발/.venv/Scripts/python.exe",
  "enableGoogleDriveUpload": true,
  "googleDriveFolderId": "1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p",
  "googleServiceAccountJsonPath": "d:/00.개발/02.up_valuation/keys/service_account.json"
}
```

### 6.3) 파일 저장
- Ctrl+S 저장

---

## 🧪 Step 7: 동작 확인

### 7.1) 테스트 실행
PowerShell에서 다음 명령 실행:

```powershell
Set-Location "d:\00.개발\02.up_valuation"
./run_daily.ps1 --limit 10
```

### 7.2) 로그 확인
터미널에서 다음과 같은 메시지를 찾습니다:

**성공 시:**
```
[Drive] Completed: X file(s) created, Y file(s) updated
```

**인증 오류 시:**
```
[Drive] Error: [에러메시지]
```
→ 폴더 공유 설정이나 경로 확인 필요

**자동 스킵 (설정 안 함):**
```
[Info] Google Drive upload skipped...
```
→ `enableGoogleDriveUpload: true` 확인, JSON 경로 확인

### 7.3) Google Drive에서 확인
- Google Drive 폴더 열기
- 다음 파일들이 업로드되었는지 확인:
  - `상세리포트_2026-04-24.csv`
  - `종목선정_핵심근거_2026-04-24.csv`
  - `최종매수_30일타임라인_2026-04-24.csv`
  - `최종매수_전일비교_2026-04-24_vs_2026-04-23.csv`
  - 기타 output 파일들

---

## 📱 Step 8: 핸드폰에서 확인

### 8.1) Google Drive 앱 설치
- iPhone: App Store에서 "Google Drive" 설치
- Android: Play Store에서 "Google Drive" 설치

### 8.2) 폴더 접근
- Google Drive 앱 → 폴더 목록에서 `UP_Valuation_Reports` 선택
- 매일 08:30 이후 새로운 CSV 파일 확인

### 8.3) 파일 보기
- CSV 파일 탭 → Google Sheets로 열기 (웹 프리뷰)
- 또는 다운로드하여 Excel로 열기

---

## 🔧 트러블슈팅

| 문제 | 원인 | 해결 방법 |
|------|------|---------|
| `[Drive] Error: Permission denied` | Drive API 미활성화 | Step 2에서 API 활성화 확인 |
| `[Drive] Error: File not found` | JSON 경로 오류 | `googleServiceAccountJsonPath` 경로 확인 |
| `[Drive] Error: Folder not found` | 폴더ID 오류 또는 공유 안 됨 | `googleDriveFolderId` 재확인, 폴더 공유 재확인 |
| 파일이 업로드되지 않음 | 설정 파일 미저장 | 파일 저장 후 파이프라인 재실행 |
| `enableGoogleDriveUpload: false` | 설정 미활성화 | JSON 파일에서 `true`로 수정 |

---

## 📝 참고 사항

1. **서비스 계정 이메일은 비용 청구 없음**
   - Google Cloud 무료 사용량 범위 내 (Drive API 호출 무료)

2. **JSON 키 파일 보안**
   - `service_account.json`은 절대 GitHub/공개 저장소에 올리지 말 것
   - 로컬 컴퓨터에만 저장

3. **자동 업로드 스케줄**
   - Windows Task Scheduler: 매일 08:30 실행
   - 파이프라인 완료 후 자동 업로드
   - 같은 이름 파일은 업데이트 (중복 생성 안 함)

4. **비용**
   - 완전히 무료 (Google Drive 저장용량 15GB 기본 제공)
   - 월 CSV 파일 발생량: ~150KB (저장용량 영향 무시)

---

## ✨ 설정 완료!

모든 설정이 완료되었다면:
- ✅ Google Cloud 프로젝트 생성
- ✅ Drive API 활성화
- ✅ 서비스 계정 생성
- ✅ JSON 키 발급 및 저장
- ✅ Google Drive 폴더 생성 및 공유
- ✅ `up_valuation_config.json` 수정
- ✅ 테스트 실행 및 확인

**다음부터는 매일 08:30에 자동으로 UP Valuation 리포트가 Google Drive에 업로드됩니다!**

