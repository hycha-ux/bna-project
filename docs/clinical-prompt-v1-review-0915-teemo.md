# 임상 프롬프트 v1 확인 2가지 (티모, 2026-09-15)

대상: `docs/clinical-prompt-v1-0915-buildy.md` §3 의 1·2번. 실생성 0회(돈 0) — 코드 판독 + 레퍼런스 실사진 쌍 합성 프로브.

## 1. `composite_outside_mask` — (b)도 비추천, 임상은 합성 끄기(a) 추천

프로브: `tools/_probe_composite_0915.py` (재료 = `samples/reference/clinical/nasolabial_before_01` + `after2w_01`, **진짜로 따로 찍은 한 쌍**을 모델 출력 자리에 넣었다. 산출 = `outputs/_probe/composite_0915*.png`, 외부 웹 이미지라 리포 밖).

| 안 | 결과(눈 확인) |
|---|---|
| 현행 (팔자 마스크 밖 = Before) | After 의 눈·눈가 주름·잔머리·밝기가 Before 와 픽셀 동일. v1 규정이 통째로 지워진다(빌디 진단 맞음) |
| (b) 얼굴 안 = Before, 머리·옷·배경 = After | 얼굴 테두리·귀 옆에 **이중 윤곽**. 머리가 몇 mm 움직인 사진에 옛 얼굴 픽셀을 붙이니 가장자리가 안 맞는다. 그리고 얼굴 안의 팔자도 Before 로 돌아가 효과가 사라진다(팔자만 빼도 눈가·입가 미세 주름 차이는 지워진다) |
| (a) 합성 끄기 | 규정과 모순 없음. 대신 지키는 쪽을 **게이트**로 옮긴다 |

**구조 게이트가 진짜 사진을 떨어뜨린다**: 같은 쌍 실측 눈 중심 이동 = IPD 대비 **2.65%** · 밝기차 0.013. 현행 `landmark_align_pct: 2.0` 이면 레퍼런스 자체가 탈락이다. 합성을 끄면 정렬 허용을 같이 풀어야 한다(후보 4%). ⚠ 표본 1쌍 — 나머지 2쌍(lifting)도 재고 확정할 것.

(a) 로 가면 얼굴이 딴사람으로 흐르는 건 동일인 게이트(identity)가, 구도 붕괴는 구조 게이트가 잡는다. 합성이 막아 주던 "시술 부위 밖 이목구비 변형"은 지금 전용 자가 없다 — 필요하면 유사변환 정렬 뒤 팔자 밖 랜드마크 편차를 재는 자를 새로 둔다(덮어쓰기 대신 측정).

## 2. After 에 스타일 참조 — 가능. 단 선결 2개

- **API**: OpenAI `/images/edits` 는 입력 이미지 최대 10장, 마스크는 **첫 장**에만 적용(공식 가이드). `edit()` 에 `style_refs` 를 받아 Before 뒤에 `image[]` 로 붙이면 된다 — `generate()` 가 이미 같은 모양으로 보낸다.
- ⚠ **선결 A — 임상 기본 공급자가 실행 불가**: `providers.yaml` 임상 = gemini, `GeminiProvider.generate/edit` 는 `NotImplementedError`. 지금 실생성하면 Before 첫 콜에서 멈춘다. 당장은 `--gen openai --edit openai`(=Gemini 임상 전용 여부 결정과 한 벌).
- ⚠ **선결 B — 참조 고르기가 리그를 모른다**: `refs._rank` 는 lighting·quality·background 만 점수화. `blue_backdrop`·`clinic_wall` 참조는 태그가 똑같아 섞이고, 팔자는 Before 참조가 grey_studio 1장뿐이라 **어떤 리그를 뽑아도 회색 스튜디오 사진이 붙는다**(현재 Before 에도 해당). `samples_index.yaml` 에 `rig` 태그 + `_rank` 가 `variation["rig"]` 를 점수화해야 "세트마다 리그 고정"이 참조에서도 지켜진다.
- 참조는 남의 얼굴이다 → After 에 붙이면 동일인 점수가 내려갈 수 있다. 붙일 거면 같은 리그의 **After 시점 참조**만, 문구는 "조명·배경·질감만 참고, 얼굴은 1번 사진". 켜기 전후 identity 코사인을 같은 seed 로 비교해 판정.
- 참고(미실측): OpenAI 마스크는 알파 채널이 필요한데 `_png(mask_img)` 는 L 모드 PNG 를 보낸다. 임상을 GPT 로 돌리면 마스크 편집에서 400 또는 무시될 수 있다 — 첫 실회차에서 확인.

## 사람 결정 (성연서님)

1. 임상 합성 끄기 + 정렬 허용 2% → 4% (잠정)
2. 임상 공급자 GPT 전환 여부 (Gemini 미구현)
