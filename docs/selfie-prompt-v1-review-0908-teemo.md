# 셀카 프롬프트 v1 실측 + 확인 6종 답변 (티모, 2026-09-08)

대상: 빌디 `5e0f838` / `docs/selfie-prompt-v1-0908-buildy.md`
재현: `PYTHONPATH=src python -m bna.cli --treatment nasolabial --mode selfie --count 8 --seed 5 --dry-run`
실제 생성: seed 5 의 **idx 2 (직후 · 한국 60대 · marked)** 와 **idx 0 (1주 후 · 한국 30대 · mild)** 를
GPT(gpt-image-2)·Gemini(2.5-flash-image) 각각으로 Before/After = **4쌍 8장**.
산출물: `C:\Users\medib\teemo\out\gen0908\` (`{gpt,gem}_{A,B}_{before,after}.png`, 합본 2장)

> 생성은 티모 폴더에서 돌렸습니다. GPT 는 티모에 OpenAI 키가 없어 **Higgsfield 경유 `gpt_image_2`** 로 뽑았고,
> After 는 Before 의 job_id 를 레퍼런스로 넘겼습니다(파이프라인의 `identity_reference` 경로와 같은 모양).

---

## 0. 한 줄 결론

프롬프트 v1 의 방향(목적 규정형 Before · 시점별 드리프트 · 프레이밍 축)은 **맞습니다.**
다만 **모델이 갈립니다 — 프레이밍 축 준수 GPT 4/4, Gemini 0/4.** 레퍼런스(후기 앱) 룩이 목표면
셀카 기본 생성기는 GPT 로 가야 합니다. 그리고 그 룩에 가까워질수록 **동일인 자동 게이트가 죽습니다**(§1).

## 1. 실측표

| 항목 | GPT(gpt-image-2) | Gemini(2.5-flash-image) |
|---|---|---|
| framing 축 준수 | 4/4 | **0/4** (늘 얼굴 전체를 그림) |
| 후기 앱 느낌(비뚤·무성의·부분 크롭) | 4/4 | 1/4 |
| InsightFace 얼굴 검출 | **0/4** (전량 미검출) | 4/4 |
| 동일인 코사인(문턱 0.60) | 판정 불가 | A쌍 0.679 통과 / **B쌍 0.507 하드 페일** |
| 직후 피부 상태 잠금(육안) | 유지됨(뺨 홍조·기미 위치 동일) | **실패**(얼굴이 통째로 매끈·어려짐) |
| 팔자가 화면에 보이는가 | A쌍 O / **B쌍 X** | A쌍 O / B쌍 △(측면이라 거의 안 보임) |

→ **4쌍 중 동일인 게이트가 유효하게 작동한 건 1쌍(25%)** 입니다.

## 2. 확인 6종 답변

### 1) 부분 크롭 vs 동일인 → **(a)+(b) 조합, (c)는 안 함**

실측이 답을 정해 줬습니다. 부분 크롭·초근접에서 InsightFace(det 640)가 **얼굴을 아예 못 잡습니다**(GPT 4장 전량).
이건 "다른 사람"이 아니라 **"판정 불가"** 인데, 지금 `identity.check` 는 검출 실패를 `score=None → hard_fail=False`
로 흘려보내므로 **게이트가 조용히 무력화**됩니다(막는 게 아니라 안 재는 것).

- **(a) 프레이밍별 identity 문장 분기 — 채택.**
  눈이 프레임 안인 프레이밍(`full_face`·`forehead_cut`·`nose_to_neck`)만 "same eyes …" 유지,
  `one_cheek`·`lower_face` 는 눈·눈썹 문장을 빼고 **코 옆선·입·턱선·모반·피부톤·솜털 결**로 대체.
  지금은 눈이 없는 컷에 "same eyes"를 요구해 모델이 눈을 프레임 안으로 끌고 들어옵니다(Gemini B After 실측).
- **(b) 게이트 축을 프레이밍에 따라 갈기 — 채택.**
  `identity.check` 가 `gate: "ok" | "fail" | "n/a"` 3값을 내고, `n/a`(미검출)면 하드 페일이 아니라
  **비전 채점으로 폴백**하되 통계에 `n/a` 비율을 남깁니다(지금은 흔적조차 안 남습니다).
  그리고 문턱 0.60 은 정면-정면 전제입니다 — 각도가 벌어진 B쌍이 0.507 로 떨어졌습니다.
  **각도 차가 있는 쌍의 문턱은 따로 재야 합니다**(실사진 쌍으로 캘리브레이션, 지금 값은 초안이라고 코드에도 적혀 있습니다).
- **(c) 눈 모자이크 — 안 합니다.**
  후기 앱이 모자이크하는 이유는 실환자라서입니다. 우리는 합성 인물이라 가릴 개인정보가 없고,
  모자이크는 동일인 문제를 **더 악화**시킵니다(볼 수 있는 근거가 줄어듦). 스타일 옵션으로만 남기면 됩니다.
- **추가 제안(비용 +1콜/세트): 앵커 컷.**
  세트마다 같은 세션에서 `full_face` 앵커 1장을 같이 뽑아 **검증 전용**으로 쓰고 배포엔 안 씁니다.
  부분 크롭 Before/After 를 각각 앵커와 비교하면 게이트가 되살아납니다.

### 2) 레퍼런스 얼굴만 크롭 → **가능. 단 폴백 필수, 그리고 절반만 해결됩니다**

`batch.run_item` 의 `identity_reference` 경로가 `before_b`(원본 바이트)를 그대로 넘기므로,
그 앞에 얼굴 bbox 크롭(여유 15~20%)을 한 단계 끼우면 됩니다.

⚠ 함정 둘:
- `landmarks.detect` 가 **이 PC에서 죽습니다** — 설치된 mediapipe 에 `mp.solutions` 가 없습니다(Tasks API 전용 빌드).
  크롭은 InsightFace bbox 로 하면 우회됩니다.
- 그런데 **부분 크롭 컷은 InsightFace 도 얼굴을 못 잡습니다** → 못 잡으면 원본 그대로 넘기는 **fail-open** 이어야 합니다.
- 효과는 절반입니다. GPT A After 는 레퍼런스가 이미 얼굴 위주였는데도 **잔머리가 그대로 복사**됐습니다.
  크롭 + `after_day` 의 "loose strands do not match" 문장을 **문단 앞쪽으로** 올리는 걸 같이 가야 합니다.

### 3) 직후 컷 각도 고정 → **고정하지 마세요. 충돌이 실재하지 않습니다**

`composite_outside_mask` 는 `spec["generation"] == "edit"` 일 때만 돕니다(`batch.py`).
셀카는 `identity_reference` 라 **그 함수를 아예 타지 않습니다.** 딜레마가 성립하지 않습니다.

실측도 같은 방향입니다 — GPT A 는 각도를 살짝 바꾸고도 뺨 홍조·기미 위치를 지켰고,
Gemini A 는 각도를 지키고도 피부가 통째로 매끈해졌습니다. **직후 잠금 실패는 각도가 아니라 모델 문제입니다.**
나중에 셀카에도 마스크 합성을 쓰고 싶어지면 그때는 각도 고정이 전제이므로 **별도 모드**로 여세요.

### 4) 배경별 허용 맥락 표 → **필요. 그리고 축이 하나 더 있습니다**

배경×맥락만으론 부족합니다. **프레이밍×맥락**이 같은 빈도로 깨집니다(실측 2건):
- A Before: `forehead_cut`(이마가 잘림) + `cap`("이마에 챙 그림자") → **없는 이마에 그림자**
- B After: `lower_face`(눈이 프레임 밖) + `cap` → Gemini 가 모자도 눈도 다 그렸습니다

**그리고 더 급한 결함을 하나 찾았습니다.** `mode_rules.selfie` 에 `context` 화이트리스트가 없어
`list(options)` 전량이 허용되고, 그 안에 **"시술 직후 After 전용" 맥락 4종이 그대로 들어 있습니다.**
400 표본 실측 — **Before 컷의 35.8% 가 직후 전용 맥락을 답니다**
(`clinic_headband` 40 · `hair_flat_after` 37 · `cotton_pad` 36 · `outing_top` 30).
`cotton_pad`(시술 부위 화장솜·연고)는 **시술 전 사진에 시술 흔적**입니다. seed 5 의 idx 3 Before 가 실제로
`hair_flat_after`("시술베드에 누워 눌린 머리")였습니다.

제안: 표 2개 + 화이트리스트 1줄.
```yaml
mode_rules:
  selfie:
    context: [none, pajamas, home_tee, towel_headband, cap, necklace, hair_in_face, finger_on_cheek]

context_allow:            # 배경 × 맥락
  home:       [none, pajamas, home_tee, hair_in_face, necklace, finger_on_cheek, towel_headband]
  bathroom:   [none, towel_headband, pajamas, home_tee, hair_in_face, finger_on_cheek]
  cafe:       [none, outing_top, cap, necklace, hair_in_face]
  outdoor:    [none, outing_top, cap, necklace, hair_in_face]
  car:        [none, outing_top, cap, necklace, hair_in_face]
  car_after:      [none, outing_top, hair_flat_after, cotton_pad, necklace]
  clinic_waiting: [none, outing_top, clinic_headband, hair_flat_after, cotton_pad]
  clinic_mirror:  [none, outing_top, clinic_headband, hair_flat_after, cotton_pad]
  clinic_bed:     [none, clinic_headband, hair_flat_after, cotton_pad]

framing_ban:              # 프레이밍 × 맥락 (그 부위가 화면에 없으면 금지)
  lower_face:   [cap, towel_headband, clinic_headband]
  one_cheek:    [cap, towel_headband, clinic_headband, necklace]
  nose_to_neck: [cap, towel_headband, clinic_headband]
```
`sample_variation`/`drift_after` 가 `background_lighting` 을 거르는 자리에서 같은 모양으로 한 번 더 거르면 됩니다.

### 5) before_severity ↔ effect_level 짝 → **필요. 아래 표를 제안합니다**

```yaml
# treatments.yaml
effect_by_severity:
  mild:     [subtle]
  moderate: [subtle, moderate]
  marked:   [moderate, dramatic]
```
근거: 실측 B쌍이 `mild` + `moderate`("noticeably shallower") 조합이었는데,
Before 에 얕은 선 하나뿐이라 After 가 **"개선"이 아니라 "다른 사진"** 으로 읽혔습니다.
⚠ 구현 순서 주의 — 나이 연동으로 severity 를 하향한 **뒤에** 짝을 뽑아야 합니다(지금 코드는 severity 하향이 먼저라 자리는 맞습니다).

### 6) C3 재확인 세트에 부분 크롭·측면 포함 → **접수. 이번 8장이 그대로 시료입니다**

측면 2장 · 부분 크롭 4장이 이미 나왔습니다(`out/gen0908/`).
⚠ 다만 이 PC 에서 `landmarks.detect` 가 죽으므로(§2-2) 마스크 재확인은 티모 쪽 Tasks API 경로로 돌립니다.
⚠ 그리고 판정 전 전제를 하나 더 걸어야 합니다 — **그 프레이밍에서 시술 부위가 화면에 있는가.**
GPT B 쌍은 팔자가 **프레임 밖**이라 마스크 이전에 전후 비교 자체가 불가능했습니다.

## 3. 요청 밖이지만 같이 고쳐야 하는 것

7. **`mode_extra.selfie` 가 Before 에만 들어갑니다.** "폰이 보이지 않는다 / 잘 나오려는 의도 없음" 규정이
   `before.md` 의 `{mode_extra}` 로만 주입되고 `after_selfie.md` 엔 없습니다 →
   **Gemini B After 에 폰이 대놓고 찍혔습니다.** After 템플릿에도 같은 규정 문장이 필요합니다.
8. **프레이밍 × 시술 부위 가시성.** `one_cheek`·`lower_face` 로 잘 뽑힐수록 팔자가 프레임 밖으로 나갑니다.
   `treatments.yaml` 에 시술별 `framing_allow` 가 필요합니다(팔자: `full_face`·`forehead_cut`·`lower_face`·`nose_to_neck`,
   `one_cheek` 은 각도가 `selfie_3q`·`front` 일 때만).
9. **aspect 폴백 표.** `output.aspect: "4:5"` 인데 `gpt_image_2` 는 4:5 를 지원하지 않아 3:4 로 냈습니다.
   프로바이더별 지원 비율 표와 최근접 폴백이 필요합니다(지금은 조용히 다른 비율이 나옵니다).

## 4. 다음 라운드 제안 (연서님 2차 판단 뒤)

- §2-4 의 3표(화이트리스트·`context_allow`·`framing_ban`)와 §2-5 짝 표는 **빌디가 config 만 고치면 끝**입니다.
- §2-1(a)(b)·§3-7 은 프롬프트 템플릿 + `identity.py` 수정 — 나눠 가져도 되고 티모가 해도 됩니다.
- 확정 뒤 같은 seed 로 8쌍 재생성해 **전/후 준수율 표**를 다시 냅니다.
