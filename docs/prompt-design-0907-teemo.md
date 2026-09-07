# 카테고리별 프롬프트 설계 방안 — 셀카용 먼저, 임상용 다음 (티모, 2026-09-07)

요청: 성연서님 — "각 카테고리별 프롬프트 설계 방안 제시. 우선 셀카용부터 잡아가고 임상용으로 넘어가면 좋을 듯"
근거: 커밋 `55b5eb8` 기준 `config/*` · `src/bna/spec.py` 실행 실측(dry-run 300~500회 표본). 문서만 읽고 쓴 게 아니라 **실제로 프롬프트를 뽑아 보고** 씁니다.

---

## 0. 한 줄 결론

셀카용의 문제는 "After 문장을 어떻게 잘 쓰나"가 아닙니다. **①Before가 시술을 모르고 ②장면이 효과를 가리고 ③표정 축이 아예 없다** — 이 셋입니다.
그래서 카테고리마다 채울 칸을 **4개**로 정의했습니다: `before_condition` · `must_not_change` · `visibility_gate` · `drift_lock`.
**임상용은 이 4칸 중 앞의 둘을 그대로 물려받고, 뒤의 둘은 촬영 리그가 대신합니다.** 그래서 셀카용을 먼저 잡는 순서가 맞습니다 — 셀카가 어려운 쪽이고, 거기서 정한 문장이 임상으로 그대로 내려갑니다.

한 줄 원칙: **Before와 After의 차이는 시술이 만든 것만 남아야 합니다.** 표정·조명·화질이 같이 바뀌면 사람 눈엔 그게 먼저 보이고, 그게 "AI 티"이자 "과장 광고"의 정체입니다.

---

## 1. 실측 — 지금 어디가 어긋나 있나

| # | 잰 것 | 값 | 뜻 |
|---|---|---|---|
| 1 | 시술 6종의 Before 프롬프트 **고유 개수** | **1 / 6** | 팔자주름 Before와 모공 Before가 **글자 하나까지 같습니다.** Before는 시술을 모릅니다 |
| 2 | 피부결 시술 효과가 **안 보이는 셀카 장면** 비율 (500회) | **71.6%** | 어두움·저화질·필터 중 하나 이상. 모공/스킨부스터는 그 장면에서 변화가 물리적으로 안 보입니다 |
| 3 | 셀카 After가 **병원 벽**으로 드리프트 (300회) | **9.3%** | 코드 결함. 셀카 After 장면을 뽑을 때 셀카 제약(`mode_rules`)을 안 봅니다 |
| 4 | 남성인데 단발/긴 생머리 (300회) | **20.7%** | 성별 제외 목록에 `bob`·`long_straight`가 빠져 있습니다 |
| 5 | **표정 축** | **0개** | 축 자체가 없고, After 프롬프트엔 "표정이 조금 달라져도 된다"가 박혀 있습니다 |

②③④⑤는 오류가 안 납니다. 조용히 통과해서 **생성비만 쓰고 검수에서 떨어지는** 자리입니다.

⚠ 특히 ⑤가 위험합니다. 팔자주름은 웃으면 누구나 깊어집니다. Before를 웃는 얼굴로, After를 무표정으로 뽑으면 **시술 없이도 완벽한 Before/After가 나옵니다.** 지금 프롬프트는 그렇게 되도록 *지시*하고 있습니다(`Natural expression, may differ slightly from the reference`). 리프팅도 같습니다 — 아래에서 찍고(Before) 위에서 찍으면(After) 시술 없이 턱선이 올라갑니다.

쉽게 말하면, 지금은 **키를 잰다면서 Before는 맨발로, After는 구두 신고 재는** 상태입니다.

---

## 2. 카테고리 프롬프트의 4칸 (설계 골격)

시술 하나당 아래 4칸을 채웁니다. 지금은 `after_change` 한 칸만 있습니다.

| 칸 | 무엇 | 왜 필요한가 | 없으면 |
|---|---|---|---|
| **1. `before_condition`** | 시술 전 *문제 상태* 문장. 강도 2단계(`mild`/`marked`) | Before에 고칠 게 있어야 After에 보여줄 게 생깁니다 | 깨끗한 얼굴이 Before로 나와 `effect_visible` 탈락 → 재생성비 |
| **2. `must_not_change`** | 그 시술이 **절대 안 건드리는** 부위 (음성 앵커) | 모델은 "예쁘게"를 시키면 얼굴 전체를 손봅니다 | 필러 넣으랬더니 코까지 높아짐 = 과장 광고 |
| **3. `visibility_gate`** | 그 효과가 **보이는 장면만** 허용 (조명·화질·각도·색감) | 모공 개선은 저화질 야간 셀카에서 물리적으로 안 보입니다 | 실측 71.6%가 헛돈 |
| **4. `drift_lock`** | Before→After 사이 **바뀌면 안 되는 축** (표정·각도·색감…) | 차이가 시술 때문인지 조명 때문인지 구분이 됩니다 | 가짜 B&A. 블라인드 테스트에서 바로 걸립니다 |

---

## 3. 셀카용 — 카테고리별 설계표

### 3-1. 한눈에

| 카테고리 | 잠글 축(`drift_lock`) | 허용 장면(`visibility_gate`) | 표정 | 나이 |
|---|---|---|---|---|
| 팔자주름 | 표정 · 각도 | 조명 window/ring/fluorescent · 필터 금지 · `selfie_low` 금지 | **잠금**(무표정·입 다뭄) | 30대~ |
| 리프팅 | 표정 · **각도** · 화질 | 정면/45도만 · `selfie_high` **금지** | **잠금** | 30대~ |
| 코 리프팅 | **각도** | 45도/측면 필수 · 셀카 하이/로우앵글 금지 | 자유 | 20~40대 |
| 인중 | 표정 · 각도 | 정면/측면 · 필터 금지 | **잠금**(입 다뭄) | 20~40대 |
| 스킨부스터 엠보 | 화질 · 조명 · 색감 | 화질 flagship/mid · 조명 window/ring · **필터 금지** | 자유 | 20대~ |
| 모공 | 화질 · 조명 · 색감 | **화질 flagship만** · 조명 window/ring · 필터 금지 | 자유 | 10대후반~ |
| 홍조 | **색감** · 조명 | **색감 neutral 고정** · 조명 window/ring | 자유 | 전 연령 |
| 필러 | 각도 (+부위별) | 부위별로 다름 → 3-3 | 잠금(턱·눈밑) | 부위별 |

### 3-2. 카테고리별 문장 초안

아래는 `treatments.yaml`에 그대로 붙일 영문 초안입니다. **의료진 검토 전 초안**입니다(gap-check D-2).

**팔자주름 (nasolabial)**
- before mild: `visible nasolabial folds running from the sides of the nose to the corners of the mouth, mild but clearly present with the face at rest, faint shadow inside the fold`
- before marked: `deep nasolabial folds with a distinct crease line and clear shadow from the nose to the mouth corners, slight slackness in the skin around the mouth`
- must_not_change: `Do not change lip shape, lip volume, mouth width, nose, or jawline width. Do not smooth the rest of the face.`
- 함정: **웃음 금지.** 웃으면 누구나 팔자가 깊어져, 표정 차이가 시술 효과로 둔갑합니다.

**리프팅 (lifting)**
- before mild: `slight softening of the jawline, early jowl formation, mid-face volume starting to descend`
- before marked: `clearly sagging jawline with visible jowls, mid-face volume descended, blurred jaw contour`
- must_not_change: `Do not change bone structure, face width, or eye shape. Do not slim the face beyond lifting.`
- 함정: **하이앵글 금지.** 위에서 찍으면 시술 없이도 턱선이 올라갑니다. Before/After 각도 동일 강제가 이 카테고리의 생명입니다.

**코 리프팅 (nose_lifting)**
- before: `low, flat nose bridge with an undefined rounded tip` (marked: `+ tip drooping slightly, bridge noticeably flat in profile`)
- must_not_change: `Do not narrow the nostrils or alar width. Do not change eyes, lips, or face shape.`
- 함정: **정면만으로는 코 높이 변화가 거의 안 보입니다.** 45도·측면이 필수이고, 셀카 특유의 하이/로우앵글은 코 길이를 왜곡해 제외합니다.

**인중 (philtrum)**
- before: `long philtrum with a low upper lip line and a wide gap between the nose base and the lip`
- must_not_change: `Do not change lip thickness, lip width, or the nose.`
- 함정: 웃으면 인중이 짧아 보입니다 → 표정 잠금.

**스킨부스터 엠보 (skinbooster_embo)**
- before mild: `slightly dull, dehydrated skin with uneven light reflection and fine dry lines on the cheeks`
- before marked: `dull dehydrated skin with rough texture, small flaky patches, fine crepey lines on the cheeks and under the eyes, tired uneven tone`
- must_not_change: `Do not remove moles or freckles. Do not change face shape, volume, or features. This is a hydration treatment, not a pigment or contour treatment.`
- 함정: **필터 색감 금지.** 필터가 이미 피부를 매끈하게 만들어 **Before가 After처럼** 나옵니다.

**모공 (skin_pores)**
- before mild: `visibly enlarged pores on the cheeks and around the nose, slightly rough skin surface`
- before marked: `pores clearly open and dense across the cheeks, orange-peel skin texture, uneven surface`
- must_not_change: `Do not change skin tone, remove moles, or alter face shape. Skin must still show real texture after treatment.`
- 함정: **모공은 화면에서 몇 픽셀이냐의 문제**입니다. 저화질·야간에서는 Before조차 모공이 안 보입니다 → 화질 flagship 고정.
- ▶ 별도 제안: 모공·홍조는 **얼굴 전체 컷 + 볼 부분 확대 컷** 2장 세트로 뽑는 게 실효가 큽니다(실제 후기가 그렇게 씁니다).

**홍조 (skin_redness)**
- before: `noticeable redness across both cheeks and around the nose, blotchy uneven flushing with visible fine capillaries`
- must_not_change: `Do not lighten overall skin tone or whiten the face. Only the redness pattern changes; tone, texture and moles stay the same.`
- 함정: **색감 축이 이 시술의 효과와 직접 충돌합니다.** 따뜻한 색감은 홍조를 만들고 차가운 색감은 지웁니다 — Before/After 사이에 색감이 바뀌면 그건 시술이 아니라 **화이트밸런스**입니다. 색감 `neutral` 고정이 필수입니다.

### 3-3. 필러는 지금 구조로는 프롬프트를 쓸 수 없습니다 (구조 변경 1건)

`filler` 는 부위가 `(specify per request)`, 마스크가 `custom`(정의 없음 = 조용히 마스크 없이 진행, gap-check C-2)입니다.
**볼 꺼짐 · 무턱 · 눈밑 꺼짐은 Before가 완전히 다른 사진**이라 한 칸으로는 `before_condition`을 쓸 수 없습니다.

→ **`filler_cheek` · `filler_chin` · `filler_undereye` 3종으로 분할**을 제안합니다.

| 부위 | before_condition | must_not_change | 각도 |
|---|---|---|---|
| 볼 | `flat, slightly hollow cheeks with lost volume, mild shadow under the cheekbone` | 얼굴 폭 · 광대뼈 구조 | 정면 · 45도 |
| 턱 | `receding short chin, weak forward projection, blunt chin-to-neck line` | 턱뼈 각도 · 입술 | **측면 · 45도 필수** |
| 눈밑 | `hollow under-eye troughs casting a dark shadow, tired look` | **다크서클 색소 자체** — 필러는 그림자를 없애지 색소를 없애지 않습니다 | 정면 · 45도 |

---

## 4. 새로 필요한 축 하나 — `expression`

지금 변주 축에 표정이 없습니다. 대신 After 프롬프트에 `Natural expression, may differ slightly from the reference` 가 고정 문구로 박혀 있어, **표정이 달라지도록 지시**하고 있습니다.

제안:
- `expression` 축 신설: `neutral_closed`(무표정·입 다뭄) / `slight_smile`(살짝 미소) / `relaxed_open`(편안한 자연 표정)
- 카테고리별 `expression_policy: lock | free`
  - `lock` (팔자·리프팅·인중·필러 턱/눈밑): Before와 After 같은 값 + After 문구를 **`identical expression to the reference`** 로 교체
  - `free` (스킨부스터·모공·홍조·코): 지금대로 자유 — 피부 시술은 표정과 무관하고, 표정이 조금 달라야 오히려 "같은 날 두 번 찍은 것"처럼 보이지 않습니다

---

## 5. 드리프트는 카테고리가 통제해야 합니다

현재 `after_drift`는 **모드 하나로만** 갈립니다(셀카 = 배경 0.7 · 조명 0.7 · 각도 0.5 · 색감 0.5 …). 그런데 **바뀌면 안 되는 축이 카테고리마다 다릅니다**(3-1 표).

→ `treatments.yaml`에 `drift_lock: [expression, angle]` 같은 목록을 두고, `drift_after()`가 그 축은 건너뜁니다.

그리고 **버그 하나**: 지금 드리프트는 셀카 제약(`mode_rules`)을 안 봐서 **셀카 After의 9.3%가 병원 벽 + 링라이트**로 갑니다(실측 300회). 화이트리스트 안에서만 뽑도록 고쳐야 합니다. 한 줄 수정입니다.

---

## 6. Before 강도 ↔ After 강도 짝 규칙

지금은 둘이 독립 추첨이라 아래 두 실패가 정상적으로 생성됩니다.

| Before | After | 결과 |
|---|---|---|
| mild (가벼움) | moderate (뚜렷) | **과장으로 보임** — 심의 위험 |
| marked (심함) | subtle (은은) | **효과 없어 보임** — 검수 탈락 |

→ 허용 짝만 뽑습니다: `(mild, subtle)` · `(marked, moderate)` · `(marked, subtle)`은 30%까지만(현실에 실제로 있는 경우라 전부 막지는 않습니다).

---

## 7. 나이 게이트

지금 나이 가중치는 **전역 하나**입니다. 그래서 *18–19세 리프팅*, *20대 초반 팔자주름*이 정상적으로 만들어집니다(실제로 dry-run 첫 표본이 18–19세 남성 스킨부스터였습니다). 그 자체가 "AI 같다"의 원인입니다.
→ 카테고리별 `age_weights` (3-1 표의 나이 칸).

---

## 8. 임상용으로 넘어갈 때 — 무엇을 물려받고 무엇이 바뀌나

| 4칸 | 셀카용 | 임상용 |
|---|---|---|
| `before_condition` | 카테고리별 문장 | **그대로 물려받음** (같은 텍스트) |
| `must_not_change` | 카테고리별 문장 | **그대로** + 마스크 합성이 픽셀로 강제 |
| `visibility_gate` | 축 제약으로 구현 | **불필요** — 리그가 이미 고정(소프트박스·5500K·85mm·무보정) |
| `drift_lock` | 축 잠금 목록 | **불필요** — 임상은 드리프트 자체가 0(같은 사진 편집) |

**즉 셀카용에서 3·4번을 잡느라 쓴 노력은 임상용에서 다시 쓰지 않습니다.** 대신 임상용엔 다른 3가지가 붙습니다.

1. **마스크 부위** — 필러가 `custom`이라 마스크 없이 통과합니다(3-3의 3분할과 함께 폴리곤을 채워야 합니다). 다른 시술은 픽셀이 보존되는데 필러만 조용히 안 됩니다.
2. **각도 세트가 카테고리마다 달라야 합니다** — 코는 측면 필수, 팔자는 정면+45도, 홍조·모공은 정면. 지금 `angles_clinical`이 대체로 맞지만 필러 3분할 후 재지정이 필요합니다.
3. ⚠ **임상 리그의 조명이 팔자·모공을 오히려 덜 보이게 합니다.** 좌우 45도 소프트박스 = **그림자 없는 평평한 빛**인데, 팔자주름과 모공은 **그림자로 보이는** 것입니다. 후기용 사진에서 "시술 전이 별로 안 심해 보인다"가 나오면 원인이 여기입니다.
   → 제안: 임상 리그에 **`side_lit` 변형 1종**(한쪽 소프트박스를 낮춘 얕은 사광)을 추가하고, 주름·모공 카테고리는 정면광 + 사광 2장을 같은 조건으로 찍습니다. 실물 촬영 규정과도 맞물리므로 성연서님·원내 확인이 필요합니다.

그리고 임상 Before는 "예쁜 셀카"가 아니라 **의무기록 사진**이라 실패 모드가 반대입니다 — 셀카는 "너무 AI 같다"가 문제고, 임상은 "너무 잘 나왔다"가 문제입니다.

---

## 9. 다음 행동 (순서 · 키 불필요)

| 순서 | 할 일 | 누가 |
|---|---|---|
| 1 | **필러 3분할** (`filler_cheek`/`chin`/`undereye`) — 구조 변경이라 지금이 제일 쌉니다 | 티모 |
| 2 | `expression` 축 신설 + `expression_policy` | 티모 |
| 3 | `treatments.yaml`에 4칸 채우기 (3-2 초안 반영) | 티모 |
| 4 | `drift_lock` 적용 + 셀카 드리프트 화이트리스트 버그 수정 | 티모 |
| 5 | 카테고리별 `age_weights` · 강도 짝 규칙 | 티모 |
| 6 | 셀카 8~10종 dry-run 눈 확인 → 문장 다듬기 | 티모 + 성연서님 |
| 7 | 임상용: 각도 세트 재지정 · 필러 마스크 · 사광 변형 검토 | 티모 (촬영 규정은 원내 확인) |

**성연서님 결정이 필요한 것 2가지**

1. **필러 부위 3종이 맞습니까?** (볼·턱·눈밑 외에 실제로 파는 부위가 더 있으면 알려주세요 — 부위마다 Before가 완전히 다릅니다)
2. **시술 문장 의료진 검토자** — 3-2는 초안입니다. 과장 표현은 광고 심의로 바로 연결됩니다.

1~5번은 "진행해" 한 마디면 바로 착수합니다(키 불필요, 반나절 규모).

---

## 부록: 실측 로그

2026-09-07, 사무실 PC. `bna-project/.venv` (python 3.12 · pyyaml 추가 설치).

| # | 무엇을 | 결과 |
|---|---|---|
| 1 | `build_prompts()` 로 시술 6종 Before 프롬프트 생성 (같은 seed) | 고유 개수 **1** — 전부 동일 문자열 |
| 2 | 셀카 500회 장면 샘플링 | 어두움/저화질/필터 = **358회 (71.6%)** |
| 3 | 셀카 After 드리프트 300회 | 배경이 `clinic` = **28회 (9.3%)** |
| 4 | 성별×헤어 300회 | 남성 + bob/long_straight = **62회 (20.7%)** |
| 5 | `variations.yaml` 축 목록 | `expression` 축 **없음** |
