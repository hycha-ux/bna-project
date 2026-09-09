# 생성 요청 대기열 — 인터넷 화면 → 생성 PC 연결 규약 (빌디, 2026-09-09)

요청: 성연서님 — "클라우드 화면에서 생성을 누르면 티모가 알아서 돌리는 구조로 설계". 화면·저장 쪽은 빌디가 만들었고(커밋 참조), **생성 PC 쪽 폴링·실행·상태 보고는 티모 몫**이다.

## 1. 한 줄

화면은 요청 한 건을 Blob `gen-requests/<id>.json` 에 적는다. 생성 PC 는 그 폴더를 주기적으로 읽어 `requested` 를 가져가 돌리고, **같은 파일을 상태만 바꿔 덮어쓴다.** 결과 사진은 지금처럼 `push-cloud` 로 올라간다.

## 2. 파일 한 건 (화면이 쓰는 형식)

```json
{
  "id": "20260909-153012-k3f9",
  "status": "requested",
  "treatment": "nasolabial", "mode": "selfie",
  "count": 8, "target_pass": 4, "cost_cap": null, "seed": null,
  "fixed": {"gender": "female"}, "simulate": false,
  "requested_by": "ys.seong@medibuilder.com", "requested_at": "2026-09-09T06:30:12.000Z"
}
```
필드 뜻은 로컬 `/api/queue/add` 의 job 과 같다(`treatment·mode·count·target_pass·cost_cap·seed·fixed·simulate`). 프로바이더(gen/edit/qa)는 안 보낸다 — `providers.yaml` 기본값 그대로.

## 3. 상태 전이 (정본: `cloud/lib/genreq.mjs` `canTransition`)

```
requested ─┬─> accepted ──> running ──> done
           │                   └──────> error
           └─> cancelled   (화면에서, requested 일 때만)
```
- 화면이 쓰는 건 `requested` 와 `cancelled` 뿐.
- 생성 PC 는 `accepted → running → done | error` 를 쓴다. **`cancelled` 가 된 요청은 돌리지 않는다**(가져가기 직전에 한 번 더 읽어 확인).

## 4. 생성 PC 가 할 일 (티모)

1. **폴링**: 60초마다 `list({prefix: 'gen-requests/'})` → 각 파일 `get` → `status === 'requested'` 인 것을 `requested_at` 순으로.
2. **받음**: 같은 경로에 `{...req, status: 'accepted', accepted_at, host}` 로 `put` (`addRandomSuffix: false`). 이 순간부터 화면의 취소 버튼이 사라진다.
3. **실행**: 로컬 `/api/queue/add` 에 `{jobs: [req 의 job 필드]}` 로 넣거나 `Batch` 를 직접 돌린다. 배치가 시작되면 `status: 'running', batch_id, started_at` 로 덮어쓰고, 진행은 선택적으로 `progress: {done, planned}` 를 같이 적는다(안 적어도 된다 — 사진은 push-cloud 로 올라가므로 화면의 작업 탭에서 보인다).
4. **끝**: `status: 'done', finished_at, batch_id, result: {total, passed, cost}` 또는 `status: 'error', error: '한 줄 사유'`.
5. **안전**: 같은 요청을 두 번 돌리지 않는다(`accepted` 로 바꾼 뒤에만 실행 · 프로세스가 죽었다 살아나면 `accepted`/`running` 인데 배치가 없는 건 `error: '중단됨'` 으로 닫는다).

Blob 토큰은 `push-cloud` 가 쓰는 `cloud/.env.local` 의 `BLOB_READ_WRITE_TOKEN` 그대로. 화면 API 를 거칠 필요 없다(로그인 쿠키가 필요해서 오히려 불편하다).

## 5. 화면 쪽 (빌디, 이미 반영)

- `GET /api/config` 에 `gen_request: true` (Blob 토큰이 있을 때). 화면은 이걸 보고 "생성 시작" 버튼을 **"생성 요청 보내기"** 로 바꾼다.
- `POST /api/gen_requests {jobs:[...]}` → 검증(`validate`) 후 저장. `GET /api/gen_requests` → 목록(진행 중 → 요청됨 → 끝난 것 순, 50개). `POST /api/gen_requests/cancel {id}`.
- 생성 탭의 대기열 카드가 인터넷 화면에서는 이 요청 목록을 보여 준다: 요청됨 / 생성 PC가 받음 / 생성 중 / 완료(결과 버튼 → 작업 탭) / 실패 / 취소.
- 회귀: `node cloud/genreq-tests.mjs` (검증·전이·정렬). 로컬(사무실 PC) 화면은 종전과 같다 — `gen_request` 가 없으면 로컬 대기열을 그대로 쓴다.

## 6. 폴러 (티모, 2026-09-09 붙임)

`ops/gen-poller.mjs` — 예약작업 **`TeemoBnaGenPoller`**(1분마다, 00:01부터 23시간 58분). §4 그대로다.
등록·재등록 = `powershell -NoProfile -File ops\register-genpoller-task.ps1`, 정의 덤프 = `ops/task-defs/TeemoBnaGenPoller.xml`.

- 상태를 읽는 곳은 로컬 큐 원장 `outputs/queue.json`(파일이라 서버가 꺼져 있어도 읽힌다), 쓰는 곳은 `genreq.mjs` 의 `advance`/`annotate` 다.
- **로컬 API 는 넣을 요청이 있을 때만 띄우고, 띄운 뒤엔 죽이지 않는다**(생성이 몇 분씩 걸린다 — 여기서 kill 하면 돈 쓰고 시작한 배치가 날아간다).
- 이중 생성 방지 넷: 락 파일 · 쓰기 직전 재확인(취소 흡수) · **라벨 `genreq:<id>`**(작업 번호를 못 적고 죽어도 다음 회차가 그 작업을 찾아 붙인다) · 한 회차 상한 10건.
- 결과는 `{total, passed, cost}`. 든 돈은 `progress.json` 항목 비용 합이고, **못 읽으면 0 이 아니라 `null`** 이다.
- 회귀 `node ops/gen-poller-tests.mjs`(25종, 네트워크 0).

- **떠 있는 로컬 API 가 옛 코드면 갈아 끼운다**(큐가 비었을 때만). 09-09 에 이걸로 한 번 데었다 — 그날 새로 생긴 `series` 칸이 오류 없이 무시돼 전·후 2장이 나왔다. 죽이는 pid 는 `spawn` 이 준 번호가 아니라 **포트를 물고 있는** 번호다(venv python.exe 는 껍데기라 둘이 다르다).
- **요청 필드가 늘면 `jobSpec` 도 늘려라.** 안 넘긴 칸은 오류 없이 기본값으로 떨어진다 — `validate`(넣는 쪽)와 `queue.py add`(받는 쪽)가 짝이다.

### 실제로 통과시킨 회차 (09-09, 전부 시뮬 모드라 돈 0)

- `20260909-153309-i113` — 요청됨 → 받음 → 생성 중 → **완료**(8/8장, 가상비용 $0.85)
- `20260909-154051-fe5s` — 도는 중에 서버를 강제로 죽여 본 것 → **실패**로 닫히고 사유가 요청에 적혔다

화면 확인용으로 이 둘만 남겨 뒀다(빌디 확인 후 지운다 — `GR.remove(token, id)`).

### 규약을 고치며 알게 된 것 두 가지 (양쪽 다 화면에도 영향)

1. **`put` 에 `allowOverwrite: true` 가 없으면 두 번째 쓰기가 통째로 실패한다**(Blob v2). 상태 전이가 곧 같은 이름 덮어쓰기라, 이게 없으면 화면의 **취소 버튼도 한 번도 성공하지 못했다.**
2. **읽기는 `useCache: false` 여야 한다.** 기본 캐시로는 완료 50초 뒤에도 목록이 '생성 중'이었다 — 폴러가 끝난 요청을 또 닫았고, 화면도 같은 옛 상태를 봤을 것이다. 둘 다 `genreq.mjs` 의 `save`/`load`/`listAll` 한 곳에서 고쳤다.

## 7. 남은 것

- 빌디: 요청 → 받음 → 완료까지 화면에서 한 번 통으로 확인(위 시료 1건이 `완료` 로 보여야 한다).
  ⚠ 시뮬 배치(`kind: sim`)는 클라우드 스냅샷에 안 올라간다 — 완료 줄의 '결과' 버튼은 **실제 생성**부터 의미가 있다.
- 예상 비용을 요청 줄에 보여 주려면 `pricing.yaml` 단가를 snapshot 에 실어야 한다(지금은 "—"). 티모 집계와 겹치니 그쪽 숫자를 받아 쓰는 게 맞다.
- 검수 흡수(`cloud/lib/reviews.mjs`)도 같은 `get` 을 쓴다 — 캐시 함정을 겪으면 여기 2번을 먼저 보라.
