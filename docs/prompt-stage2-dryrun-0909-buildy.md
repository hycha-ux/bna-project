# 2단계 dry-run 기록 — 팔자 · 코 필러 · 목주름 필러 (빌디, 2026-09-09)

방법: `--seed 5 --count 8 --dry-run` 으로 8쌍 프롬프트를 뽑아 문장 단위로 읽고, 잡힌 것을 config 로 고친 뒤 같은 seed 로 다시 뽑아 확인. 비용 0, 키 불필요.
각 항목은 selftest 에 회귀로 박혀 있다. 의료진 검토는 아직(전부 초안).

| 시술 | 잡힌 것 | 고친 곳 |
|---|---|---|
| 팔자 | 50대 남성에 단발 | `gender_exclusions.male` 에 bob·long_straight·ponytail |
| 팔자 | 30대에 새치+굵은 목+피곤 | `age_gates` 신설 (새치 40대~, 피곤 20대 후반~) |
| 팔자 | 직후 문장에 she 고정 | `after_day.same` 대명사 제거 |
| 팔자 | 규정문 "no smile" 이 표정 축과 충돌 | `mode_extra.selfie` 에서 제거, `before.md` 끝 "natural expression" 제거 |
| 팔자 | "visibly softened" + "could be missed" 모순 | 시술 문장 중립화, `effects.yaml` 강도 문구가 정도를 말함 |
| 팔자 | 미소 표정 | 팔자·리프팅·인중 `scene_allow.expression` 에서 미소 제외 |
| 팔자 | 2주 뒤 포니테일→삭발 | `hair_style_neighbors` (2주 안에 될 수 있는 모양만) |
| 팔자 | 짧은 머리에 "볼을 덮는 잔머리" | `context_hair` |
| 코 필러 | 동일인 잠금 "same nose shape" 이 시술과 모순 | `identity_exempt`·`identity_note` (코필러·코리프팅·리프팅·인중) |
| 코 필러 | 뿔테 안경이 콧대를 가림 | `axis_ban.extras` |
| 코 필러 | "코 아래만" 프레이밍은 콧대가 잘림 | `framing_allow` 를 full_face·forehead_cut 만 |
| 코 필러 | 직후 컷에 수염이 생김 | `after_immediate.extras` (같은 날 가능한 것만) |
| 목주름 | 목만 찍은 컷에 "same eyes" 잠금 → 얼굴을 끌어옴 | **프레이밍별 잠금 문장 3종** (`identity_lock_by_framing`): 전체 / 눈 밖 / 목 |
| 목주름 | "visibly softened" 모순 | 시술 문장 중립화 |

프레이밍별 잠금은 팔자·모공 등 **모든 셀카**에 적용된다 (눈이 프레임 밖인 lower_face·one_cheek·nose_to_neck 는 코·입·턱선·점 잠금). Before·After 중 더 좁은 쪽을 따른다.

## 남은 것
- 실생성 확인: `.env` 에 OPENAI_API_KEY 가 들어오면 시술당 8쌍(약 $2~3) → 학습 탭 버전 표로 전후 비교.
- 리프팅 · 인중 · 스킨부스터 · 모공 · 홍조 · 코 리프팅: `before_condition` 문장 (티모 0907 초안 있음).
- 의료진 검토: 코 필러의 "미간 꺼짐·코끝 처짐", 목주름 "2~3줄 가로 주름" 표현.
