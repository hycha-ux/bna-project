# 경과 시리즈 — 시술 전 1장 + 시점별 후 N장 (빌디, 2026-09-09)

요청: 성연서님 — "후기 사진이 전·후로 끝나는 경우도 있고 시간차 순으로 나오는 경우도 있다" → 결정: **기본 시점 직후·2주, 채택은 세트 단위**.

## 1. 한 줄

`series: ["immediate", "2w"]` 를 붙이면 세트 하나가 **시술 전 1장 + 시점마다 시술 후 1장**이 된다. 안 붙이면 종전대로 전·후 2장. 세트는 After 전부가 통과해야 통과하고, 채택·제외도 세트(item) 단위다.

## 2. 지켜야 하는 것 3가지 (코드에 박힌 규칙)

1. **효과는 시간순으로 누적된다.** 최종 강도는 강도 짝 표(`effect_by_severity`)로 정하고, 시점마다 `effects.yaml` `series_levels` 로 낮춘다: 직후 = `early`(거의 안 보이고 붓기·발적만) · 1주 = `subtle` · 2주·4주 = 최종.
2. **인물은 같고 장면은 시점마다 다르다.** 시점마다 `drift_after` 를 따로 돌린다 — 직후는 같은 날 규칙(병원·외출복·피부 상태 잠금), 1주 이후는 다른 날 규칙.
3. **동일인 기준은 항상 시술 전 사진.** 모든 After 는 Before 를 참조로 생성하고(After 를 다음 After 의 기준으로 쓰면 얼굴이 흘러간다), 동일인·구조 게이트도 Before 대비로 잰다.

## 3. 어디가 바뀌었나

| 층 | 무엇 |
|---|---|
| `config/effects.yaml` | `series_levels`, `effect_levels.early` |
| `spec.build_prompts(..., series=)` | `afters: [{when, effect_level, after_prompt, after_variation, after_parts}]`. `after_*` 는 마지막 시점(종전 호환). `series_points()` 가 시술이 허용하는 시점만 시간순으로 |
| `batch.Batch(series=)` | After 마다 생성 → 후처리 → 구조·동일인·비전 검수. `meta.after_results[when]`, `fail_reasons` 에 `@when` 접미. 파일 `*_after_<when>.jpg`. 대표 결과(마지막 시점)는 종전 키에도 |
| `queue.add` / `run_job` / `start_run` / `/api/plan` / `/api/estimate` | `series` 통과. 비용은 After 수만큼 |
| `api.after_files_of()` | 파일 → `{immediate: …, 2w: …}` (시리즈 아니면 `{final: …}`), `after_file` = 마지막 시점. 라이브러리·내보내기(시점 전부 복사) |
| 화면 | 생성 조건 **사진 구성**(전·후 2장 / 경과 시리즈 + 시점 칩, 고른 시술이 허용하는 시점만). 미리보기는 시점별 프롬프트. 격자 카드에 "N시점" 배지. 검수 모드에 **시점 pill**(탈락 시점은 ✕) + "채택·제외는 세트 단위" 안내 |
| 클라우드 요청 | `genreq.validate` 가 `series` 를 받는다(시간순·아는 값만) |
| 회귀 | `selftest.py` ⑳ · `cloud/genreq-tests.mjs` |

## 4. 비용

세트 = 생성 1 + (After 생성 + 검수) × 시점 수. 직후·2주면 전·후 2장의 약 1.7배. 그래서 기본은 전·후 2장이고 시리즈는 골라서 쓴다.

## 5. 티모 확인 사항

- `batch.run_item` 의 After 구간을 루프로 바꿨다. **다음 실생성 전에 pull.** 시리즈를 안 쓰면(`series` 없음) 종전과 같은 파일·메타가 나온다.
- 검수 재시도는 세트 전체를 다시 뽑는다(한 시점만 다시 뽑지 않는다) — 단순하게 갔다. 비용이 걱정되면 시점별 재시도로 바꿀 수 있다.
- 클라우드 요청 폴러는 `series` 필드를 그대로 `/api/queue/add` 에 넘기면 된다.
