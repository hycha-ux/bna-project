# 프롬프트 구조 v2 — 1단계 구조 작업 (빌디, 2026-09-09)

요청: 성연서님 — "진행해, 0단계부터" → "필러는 코필러·목주름필러 두 개만 우선"
근거: 티모 설계안(`prompt-design-0907`)의 4칸 + 리뷰(`selfie-prompt-v1-review-0908`)의 표 3개 + 동일인 게이트 문서의 `framing_allow`.
0단계(계측)는 `4439cfc` — 학습 탭에 **프롬프트 버전별 성적표**. 이 문서의 변경은 새 버전 줄로 잡힌다.

---

## 0. 한 줄

설계 문서는 있었는데 config 에는 팔자 `before_condition` 하나뿐이었다. **문장 다듬기 전에 구조부터** 넣었다 —
시술별 제약이 **추첨(sample_variation·plan_batch) · 드리프트(drift_after) · 조립(build_prompts)** 세 곳에 같은 규칙으로 먹는다.
실측: 시술 9종 × 300 표본, 제약 위반 **0건** (selftest ⑱ 이 120 표본으로 상시 감시).

## 1. 시술 정의에 생긴 칸 (`config/treatments.yaml`)

| 칸 | 뜻 | 없으면 |
|---|---|---|
| `before_condition` | 시술 전 문제 상태 (강도별) | Before 가 시술을 모른다 → 깨끗한 얼굴 |
| `must_not_change` | 절대 안 건드리는 곳. After 지시문 뒤에 붙는다 | 얼굴 전체를 손본다 = 과장 광고 |
| `scene_allow` | 효과가 **보이는** 장면만 (조명·화질·색감·각도) | 모공이 야간 저화질에서 안 보인다 (실측 71.6% 헛돈) |
| `drift_lock` | Before→After 사이 **안 바뀌는** 축 | 표정·각도 차이가 시술 효과로 둔갑 |
| `framing_allow` | 시술 부위가 화면에 남는 프레이밍 | one_cheek 팔자 = 부위 밖 (0908 실비용 $2.28) |
| `framing_ban_by_angle` | 각도별 금지 프레이밍 | 측면 + 한쪽 볼 = 부위 사라짐 |
| `context_ban` | 부위를 가리는 소품 | 목걸이가 목주름을 가린다 |
| `expression_policy` | `lock` / `free` | 웃으면 누구나 팔자가 깊어진다 |
| `age_weights` | 시술별 나이 가중. **0 = 안 뽑음** | 18세 리프팅 = AI 티 |
| `effect_by_severity` | Before 강도 ↔ After 효과 허용 짝 | mild+눈에 띄게 = 과장, marked+은은 = 효과 없음 |

`before_condition` 이 있는 건 **팔자 · 코필러 · 목주름필러** 3종. 나머지 6종은 구조 필드만 넣었고 문장은 2단계.

## 2. 필러 2분할

`filler`(부위 미정, 마스크 `custom` = 조용히 마스크 없이 진행) → **`filler_nose` · `filler_neck`**.

| | 코 필러 | 목주름 필러 |
|---|---|---|
| Before | 낮고 평평한 콧대·둥근 코끝 (mild/marked) | 목 앞 가로 주름 2~3줄 (mild/marked, 40대~ marked) |
| 안 건드림 | 콧볼 폭·눈·입·얼굴형 | 턱선·턱·얼굴·목 길이, 미백 금지 |
| 각도 | 45도·측면만 (정면은 코 높이 안 보임) | 턱 든 각도·정면·45도 (`selfie_high` 는 목이 안 보임) |
| 프레이밍 | 코 전체가 있는 3종 | `nose_to_neck` + **신설 `neck_only`**(턱~쇄골) |
| 잠금 | 각도 | 각도 (턱 들고 내리는 것만으로 주름이 생기고 사라진다) |
| 마스크 | `nose` (기존) | **`neck` 파생 영역** — 랜드마크에 목이 없어 턱선을 얼굴 높이 55% 만큼 내린 사다리꼴 |

⚠ 목주름 셀카는 얼굴이 대부분 프레임 밖이라 동일인 자동 게이트가 `n/a` 로 나온다 (identity-gate 문서 L4). 비전 채점의 identity 항목만 남는다 — 통계에 `measured_rate` 로 보인다.
⚠ 임상 모드의 프레이밍은 리그가 `full_face` 고정이라 목주름 임상 컷은 촬영 규정(턱~쇄골 컷) 확인이 필요하다. 4단계(임상) 항목.

## 3. 변주 축에 생긴 것 (`config/variations.yaml`)

- **`expression` 축 신설**: 무표정·살짝 미소·편안한 표정. 임상은 무표정 고정. 상담 사진은 대부분 무표정이라 가중 3:1:2.
  `lock` 시술(팔자·리프팅·인중)은 After 에 `Identical expression to the reference: … must not change at all` 이 들어가고, 기존의 "may differ slightly" 문장은 `free` 시술에만 남는다.
- **`context_allow`** (배경 × 맥락): "차 안 + 수건 헤어밴드" 같은 조합 차단.
- **`framing_ban`** (프레이밍 × 맥락): "이마 잘림 + 모자 챙 그림자" 차단.
- **`neck_only`** 프레이밍 — `framing_allow` 로만 진입 (목주름 필러 전용).
- After 셀카 템플릿에 **셀카 규정 문장이 After 에도** 들어간다 (0908 실측: After 에 폰이 찍힘).

## 4. 코드

- `spec.treatment_rules()` — 시술 제약 한 뭉치. `spec.allowed_values()` — 한 축의 허용 목록을 8단계로 거른다. 추첨·플래너·드리프트가 **같은 함수**를 쓴다(같은 판정이 두 곳이면 반쪽만 고쳐진다 — identity/structure 교훈).
- `plan_batch(..., treatment=)`, `sample_variation(..., treatment=)`, `drift_after(..., treatment=)` — CLI·API·배치 전부 넘긴다. 안 넘기면 예전처럼 모드 규칙만.
- `spec.load()` 에 mtime 캐시 — 300장 계획이 분 단위에서 1초로. 파일을 고치면 바로 다시 읽는다.
- `landmarks.neck_polygon()` + `REGIONS["neck"]`.

## 5. 재현

```
PYTHONPATH=src python3 selftest.py                                                            # ⑱ 구조 v2
PYTHONPATH=src python3 -m bna.cli --treatment filler_neck --mode selfie --count 8 --seed 5 --dry-run
PYTHONPATH=src python3 -m bna.cli --treatment filler_nose --mode selfie --count 8 --seed 5 --dry-run
```

## 6. 다음 (2단계)

시술별 문장 — 팔자 → 리프팅 → 인중 → 코필러 → 목주름필러 → 스킨부스터 → 모공 → 홍조 순으로 dry-run 눈 확인 후 8쌍 실생성, 학습 탭 버전 표로 전후 비교.
성연서님 결정 남은 것: 셀카 기본 생성기 GPT 확정 상태에서 Gemini 를 임상 전용으로 내릴지 · 의료진 검토자.
