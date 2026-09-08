# 구글드라이브 백업 — 파트장님 요청서 (2026-09-08, 티모)

성연서님 지시로 백업을 구축했습니다. **코드·예약작업은 끝났고, 남은 건 구글 계정 권한 하나**입니다.
아래 A안(권장)이 되면 A로, 안 되면 B로 가면 됩니다. 둘 다 **10~15분**입니다.

준비물이 도착하면 티모가 첫 백업을 돌려 결과를 스레드에 보고합니다.

---

## A안 (권장) — 공유 드라이브 + 전용 서비스 계정

> 서비스 계정은 사람이 아닌 '프로그램용 계정'입니다. 사고가 나면 이것만 폐기하면 되고,
> 파트장님 개인 계정과 분리됩니다. **단 서비스 계정은 제 저장용량이 0이라 공유 드라이브가 필요합니다.**

1. **공유 드라이브 만들기** — drive.google.com → 왼쪽 `공유 드라이브` → `새로 만들기` → 이름 `B&A 백업`
   - 왼쪽에 `공유 드라이브` 메뉴가 안 보이면 → **B안으로 가세요**(요금제에 없는 기능입니다).
2. **구글 클라우드 콘솔** console.cloud.google.com → 프로젝트 새로 만들기 → 이름 `bna-backup`
3. `API 및 서비스` → `라이브러리` → **Google Drive API** 검색 → `사용 설정`
4. `사용자 인증 정보` → `사용자 인증 정보 만들기` → **서비스 계정** → 이름 `bna-backup` → 만들기
5. 만들어진 서비스 계정 클릭 → `키` 탭 → `키 추가` → `새 키 만들기` → **JSON** → 다운로드
   (파일 안에 `...@....iam.gserviceaccount.com` 형태의 메일 주소가 있습니다)
6. 1번 공유 드라이브로 돌아가 → `멤버 관리` → 5번의 **서비스 계정 메일 주소**를 추가 →
   권한 **콘텐츠 관리자**
7. 그 공유 드라이브를 열고 주소창의 마지막 조각(= **폴더 ID**)을 복사합니다.
   `https://drive.google.com/drive/folders/`**`0AB...`** ← 굵은 부분

8. **전달** — 메모장으로 `C:\Users\medib\_teemo_keys.txt` 를 만들어 두 줄을 적어 주세요.

   ```
   GOOGLE_SA_JSON_B64=<아래 명령이 뱉는 한 줄>
   GDRIVE_BACKUP_FOLDER_ID=<7번에서 복사한 값>
   ```

   JSON 을 한 줄로 바꾸는 명령(PowerShell, 다운로드한 파일 경로만 바꾸세요):

   ```powershell
   [Convert]::ToBase64String([IO.File]::ReadAllBytes("$HOME\Downloads\bna-backup-xxxx.json")) | Set-Clipboard
   ```

   붙여넣고 저장한 뒤 → `node C:\Users\medib\teemo\install-keys.mjs`
   (티모 금고로 옮기고 **원본 txt 는 덮어쓴 뒤 삭제**합니다. 값은 화면에 안 찍힙니다.)

---

## B안 — 개인 드라이브 + 계정 위임 (공유 드라이브가 없을 때)

> 파트장님 계정의 권한을 프로그램에 한 번만 빌려주는 방식입니다. 파일 주인은 파트장님이 됩니다.

1. drive.google.com 내 드라이브에 폴더 `B&A 백업` 생성 → 열고 주소창 마지막 조각(**폴더 ID**) 복사
2. console.cloud.google.com → 프로젝트 `bna-backup` → `Google Drive API` 사용 설정 (A안 2~3번과 동일)
3. `OAuth 동의 화면` → **내부(Internal)** 로 만들기 (medibuilder.com 계정만 쓰므로 심사 불필요)
4. `사용자 인증 정보` → `OAuth 클라이언트 ID` → 유형 **데스크톱 앱** → 만들기 →
   **클라이언트 ID·클라이언트 보안 비밀** 확인
5. 파트장님 PC에서 아래 한 줄 실행 → 브라우저가 열리면 로그인 후 `허용`

   ```
   node C:\Users\medib\bna-project\ops\drive-oauth-setup.mjs --client-id <ID> --client-secret <비밀> --folder <폴더ID>
   ```

   → 필요한 줄을 `_teemo_keys.txt` 에 자동으로 적습니다(값 미출력).
6. 이어서 `node C:\Users\medib\teemo\install-keys.mjs`

---

## 이미 끝나 있는 것 (티모 몫)

- 백업 스크립트 `ops/drive-backup.mjs` — **단방향**(여기서 지운 건 드라이브에서 안 지운다),
  새것·바뀐 것만 올림, 원장 `ops/.drive-manifest.json`.
- 예약작업 **`TeemoBnaDriveBackup`** 매일 23:00. 키가 오기 전까지는 "대기" 로그만 남기고 멈춥니다
  (종료코드 3 = 고장이 아니라 '아직'). 키가 들어오면 그날 밤부터 자동으로 돕니다.
- 회귀 `node ops/drive-backup-tests.mjs` (16종) — 전부 통과.
- 대상: `outputs/`(생성물·메타) + `samples/`(참조 사진). 로그·임시·zip·exports 는 제외.
  현재 18개 파일 1.1MB, 장당 평균 182KB.

⚠ 참조 사진에 실제 인물이 섞여 있다면, 백업 폴더 공유 범위를 **필요한 사람만**으로 두세요.
