# 자동 검수 'AI 티' 항목 초안 (빌디, 2026-09-21)

> **결과 (같은 날 오후, 티모 실측 뒤):** 이 초안의 §3 `phone_real` 문항은 **폐기**. 티모가 판정 끝난 컷에 재채점해 보니
> 84장 중 81장이 "티 0개", 문구를 세게 바꿔도 정확도 61%로 채택분 절반을 죽였다(`docs/ai-look-item-0921-teemo.md`).
> 사람이 남긴 'AI 티' 메모 6건은 전부 **"각도·표정·입모양이 비포와 똑같다"** — 한 장의 질감이 아니라 **전·후가 너무 닮은 것**이었고,
> 이미 재던 동일인 유사도(≥0.82)가 그걸 가른다(걸린 19장 중 18장 사람도 탈락, 좋은 사진 1장만 잃음).
> 반영: ① 유사도 상한 0.82 **기록 전용** + 검수 화면 닮음 칩 ② 원인 쪽 — 'AI 티' 15/15 가 팔자에 몰렸고 팔자 단발은 After 표정이 0/18 바뀌던 것 →
> 표정 잠금 완화 실험(2차, 시점 2주 고정: 채택 대조 2/2 = 실험 2/2, 닮음 0.696→0.634) → 팔자 설정 `single_relax: [expression]` 정식 반영(v29, 12:50).
> §1(항목이 변별력 0)·§5(임상 채택 0)는 유효. §2 의 '질감 티' 표는 4쌍 눈 비교라 표본이 적었고 메모 근거에 밀렸다.

요청: 연서님 — 09-16 보류 "통과 기준 심화" 중 AI 티 항목. 사람 탈락 사유 1위(48건)인데 자동 게이트가 못 거른다.
근거: 클라우드 실생성 47배치 124장(09-08~09-21) 판정 + 항목별 점수, 탈락·채택 컷 4쌍 눈 비교. 실생성·재채점은 안 돌렸습니다.

---

## 1. 지금 항목은 있는데 아무것도 못 잰다

`config/qa_checklist.yaml` 에 `ai_look` 이 이미 있다 — "Overall image does not look AI-generated (no over-symmetry, waxy glow, odd artifacts)", 컷 7.

AI 통과 82장의 `ai_look` 점수 분포:

| 사람 판정 | 8점 | 9점 | 10점 | 7점 |
|---|---|---|---|---|
| **AI 티로 탈락** (30장) | 3 | 12 | 15 | 0 |
| 채택 (38장) | 2 | 29 | 5 | 2 |
| 다른 사유 탈락 (14장) | 1 | 6 | 7 | 0 |

- 사람이 AI 티로 버린 30장 중 27장이 9~10점. 채택된 것과 분포가 같다 → **변별력 0**.
- 미달(7점 미만)은 82장 중 **0건**. 이 항목은 한 번도 탈락시킨 적이 없다.
- 심사가 남긴 메모가 답을 말해 준다: "mostly photographic… **slight over-sharpness and uniformity** suggest mild AI processing" → 9점. "**mild smoothness… slight processed look**" → 9점. **티를 봐 놓고 만점에 가깝게 준다.** 문항이 "아티팩트가 있나"라서 왁스 광택·여섯 손가락 같은 사고만 찾고, 없으면 통과다.
- `skin_texture`·`hair` 도 같다 — 탈락 30장 전부 8~9점.

## 2. 사람이 'AI 티'라고 부르는 것 (탈락 4쌍·채택 2쌍 눈 비교)

| 탈락 컷에서 보인 것 | 채택 컷에서 보인 것 |
|---|---|
| 피부 톤이 얼굴 전체에 **균일** — 볼·턱·목이 한 색, 홍조·얼룩 없음 | 부위마다 톤이 다르고 잡티·붉은 기가 있음 |
| **노이즈 없이 매끈**, 그런데 머리카락·눈썹은 **선명하게 한 올씩** (렌더 특유의 '부드러운 피부 + 날카로운 선') | 전체가 폰 카메라 수준으로 **살짝 물러지고 노이즈**가 낀다 |
| 빛이 얼굴을 **고르게 감싸** 그림자 경계가 없음 | 창가·실내등 쪽으로 **한쪽이 어둡고** 그림자 경계가 있음 |
| 머리카락 덩어리가 **칠한 듯** 매끈 | 잔머리·엉킴·빛 반사 불규칙 |
| 전·후가 '같은 렌더'로 보임(둘 다 매끈) | 전·후가 '다른 날 다른 폰 사진'으로 보임 |

즉 사고성 아티팩트가 아니라 **"폰 사진이 아니라 그림"** 이라는 전체 인상이다. 문항이 그걸 물어야 한다.

## 3. 초안 — 키를 바꾸고 방향을 뒤집는다

키를 `ai_look` → `phone_real` 로 바꾼다(저장소 규칙: 뜻이 바뀌면 키를 바꿔 옛 점수와 한 열에 안 섞이게. `hands_absent` 선례).

```yaml
# 2026-09-21 ai_look → phone_real. 종전 문항은 "아티팩트가 있나"를 물어 사고성 결함만 찾았다 —
#   사람이 AI 티로 버린 30장 중 27장이 9~10점(변별력 0, 미달 0건). 심사 메모는 "over-sharpness·uniformity·
#   smoothness"를 봐 놓고 9점을 줬다. 그래서 ① '결함 찾기'가 아니라 '폰 사진으로 믿기나'를 묻고
#   ② 기본값을 통과가 아니라 **의심**으로 두고 ③ 티 하나마다 감점을 못박는다.
#   ⚠ 문항이 바뀌었으므로 이 줄 앞뒤 회차의 점수는 다른 자로 잰 값이다(옛 열은 ai_look 으로 남는다).
items:
  phone_real: >
    Would a skeptical person, told these are two ordinary phone photos of a real customer,
    believe it without hesitation? Judge the overall impression, not isolated defects.
    Start from 10 and subtract 2 for EACH of these tells present in either photo:
    (a) skin tone is uniform across the whole face and neck with no blotches, redness or
    unevenness; (b) skin is smooth and noise-free while hair, brows or lashes are rendered
    crisp strand by strand (soft skin + sharp lines); (c) light wraps the face evenly with no
    shadow edge from a window, lamp or ceiling light; (d) hair reads as painted masses rather
    than messy strands with stray hairs; (e) the before and after look like the same
    rendering rather than two separate snapshots taken on different days. A real phone photo
    usually shows slight softness, sensor noise, uneven color and at least one harsh shadow.
    Score 9-10 only if you would not suspect editing at all; 7-8 if it passes a glance but
    would not survive a second look; 6 or below if any tell is obvious.
thresholds:
  phone_real: 7      # 시작값. 4장에서 재보정 (아래 4)
```

임상(`items_clinical`)은 (c)·(e)를 빼야 한다 — 임상 리그는 고른 조명이 정상이고 전·후가 같은 부스라 '같은 렌더처럼 보임'이 감점이 되면 안 된다. 임상용은 (a)(b)(d) 셋만.

## 4. 재보정 — 새 문항을 옛 컷에 다시 물어본다

문항을 바꾸고 바로 배치에 쓰면 컷 7이 맞는지 모른다. 판정이 끝난 68장(AI 티 탈락 30 + 채택 38)에 새 문항만 다시 채점해서:

- 탈락 30장과 채택 38장의 점수 분포가 **갈리는지**(안 갈리면 문항을 다시 쓴다)
- 갈리면 두 분포 사이 어디에 컷을 두면 '채택을 버리는 비율'이 가장 낮은지 → 컷 확정

비용: 비전 호출 68회 × GPT 추정 $0.01 = **약 $0.7** (Gemini 면 $0.34). 재채점 도구는 없어서 만들어야 한다(`tools/` 에 스크립트, 배치 원장은 안 건드리고 결과만 별도 JSON).

⚠ 유료 호출이라 연서님 확인 뒤에 돌린다.

## 5. 같이 알아야 할 것

- **심사와 화가가 같은 모델이다.** 셀카는 GPT 가 그리고 GPT 가 채점한다. 자기 그림의 티를 못 보는 쪽으로 치우칠 수 있다. 문항으로 안 갈리면 다음 수는 설계 검토 B3(별도 AI 탐지기)이나 심사만 Gemini 로 바꿔 보는 것.
- **임상은 채택 0장이다.** 채택 38장이 전부 셀카고, 임상 AI 통과분은 사람이 하나도 안 골랐다(AI 티 10건). 임상은 문항 손보기보다 프롬프트·리그 쪽 문제일 가능성이 커서 따로 봐야 한다.
- `skin_texture`·`hair` 문항도 같은 병(결함 찾기 → 다 만점)이다. 이번엔 안 건드리고, `phone_real` 이 갈리는지 본 뒤 같은 방식으로 고친다.
- 사람 검수 메모가 전부 비어 있다. 'AI 티' 태그 옆에 한 단어(피부/머리/조명/렌더)만 남겨 주시면 다음 재보정 근거가 된다.
