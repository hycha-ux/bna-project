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

## 6. 남은 것

- 티모: §4 폴러 (예약작업으로, 세션이 닫혀도 살게).
- 빌디: 티모 폴러가 붙으면 요청 → 받음 → 완료까지 화면에서 한 번 통으로 확인.
- 예상 비용을 요청 줄에 보여 주려면 `pricing.yaml` 단가를 snapshot 에 실어야 한다(지금은 "—"). 티모 집계와 겹치니 그쪽 숫자를 받아 쓰는 게 맞다.
