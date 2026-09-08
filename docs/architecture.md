# 시스템 설계 (v2)

브리프의 세 축(실사 클로즈업 · 임상 동일 조건 · 대량생산)을 구조로 보장하는 설계.

## 1. 전체 흐름

```
[배치 요청]  시술 · 모드 · 목표 통과 수 · (옵션) 축 고정
     │
     ▼
[플래너]     균형 샘플링으로 변주 조합 N개 생성 (인물 11축 + 장면 5축, 중복 없음, 축 고르게 분포)  ← 구현됨
     │       예상 호출 수·비용 산출 → 시작 확인
     ▼
[워커 풀]    조합마다 아래를 병렬 실행 (동시 N건)                          ← batch.py 구현됨 (프로바이더 구현 대기)
     │   ① 프롬프트 조립 (레이어 합성 + 효과 강도·경과 시점)
     │   ② Before 생성            provider.generate(style_refs=참조 라이브러리에서 태그 매칭)
     │   ③ After 생성              임상: provider.edit(before)  셀카: provider.generate(ref=before, 드리프트된 장면)
│                             두 경우 모두 identity_lock 삽입, Before 이미지를 참조로 사용
│                             임상: 랜드마크 부위 마스크 → 마스크 밖 원본 픽셀 복원 (composite)
│   ③' 후처리                 카메라 아티팩트 (화소 축별, 세트 동일 seed)
     │   ④ 자동 검수 (3단)
     │        a. 구조 검사: 얼굴 검출 · 랜드마크 정렬 오차 · 시술 부위 프레임 내 포함 여부
     │        b. 비전 채점: 7항목 0~10 (손·피부·머리카락·동일성·드리프트·효과·AI티) · 동일성은 하드 페일
     │        c. 중복 검사: 얼굴 임베딩으로 배치 내 유사 인물 제거
     │   ⑤ 판정: 미달 → ②부터 최대 3회 재시도
     ▼
[정리]       파일명 규칙 · manifest.csv · stats.json (축·항목·프롬프트 버전별 통과율, 실패 사유, 통과당 비용)
     ▼
[갤러리]     통과작만 노출. 사람은 여기서 최종 픽 (선택)
```

## 2. 프롬프트 레이어

| 순서 | 레이어 | 임상 모드 | 셀카 모드 |
|---|---|---|---|
| 1 | 인물 | 11축: 나라·연령·성별·얼굴형·피부톤·피부상태·체형·헤어스타일·헤어컬러·눈매·기타 | 동일 (임상은 머리 묶음·노메이크업 제약) |
| 2 | 프레이밍 | 얼굴 클로즈업 계열, 세부 구도 자유 (규격 미고정) | 동일 |
| 3 | 촬영 리그 | **`clinical_rig.yaml` 고정 세트** (카메라·거리·조명·배경·자세) | 배경·각도·조명·화소 변주 |
| 4 | 피부·리얼리티 | 모공·솜털·잡티 유지, 리터칭 금지 | 동일 + 폰 카메라 처리 특성 |
| 5 | 모드 지시 | 무표정·머리 묶음·노메이크업·헤어밴드·가운 | 자연 표정, 손 없는 구도 기본 |
| 6 | 금지 | 화보 접미, 뷰티 필터, 대칭, 스튜디오 보케 | 동일 |
| — | After | identity_lock + `after_change` + 그 외 변경 금지 | identity_lock + 드리프트된 장면·헤어 + `after_change` |

브랜드 톤(prompf DB)은 사진 프롬프트에 넣지 않는다. 갤러리 UI와 최종 카드 디자인 단계에서만 사용.

## 3. 임상 동일 조건 보장 메커니즘

| 층 | 수단 |
|---|---|
| 프롬프트 | 리그 프로파일 문장을 Before/After 모두 동일하게 삽입 |
| 생성 방식 | After = Before 편집. 마스크 가능한 모델은 시술 부위만 마스크 |
| 수치 검증 | 랜드마크(눈·코·입) 위치 오차, 얼굴 크기 비율, 밝기 히스토그램 차이 → 임계 초과 시 불합격 |
| 시리즈 | 정면·45°·측면 3컷을 같은 인물 시드로 생성 (모델이 시드/참조 이미지를 지원할 때) |

## 4. 대량생산 메커니즘

| 요소 | 구현 |
|---|---|
| 샘플링 | `planner.py`: 축별 옵션을 순환 큐로 균등 배분, 배경-조명 호환·성별 제외 규칙 적용. 인물 조합 중복 0. `--fix`로 축 고정 |
| 병렬 | `asyncio` 워커 풀, 프로바이더별 동시성 상한·레이트리밋 준수 |
| 재시도 | 조합 단위 최대 3회. 실패 조합은 `failed.csv`에 사유와 함께 기록 |
| 비용 | 프로바이더별 단가표(`config/pricing.yaml`) × 예상 호출 수. 통과율 이력으로 보정 |
| 이어하기 | 배치 상태를 `state.json`에 저장. 중단 후 재실행 시 미완료 조합만 처리 |
| 정리 | `{treatment}_{mode}_{country}{age}{gender}_{id}_{before|after}.jpg`, `manifest.csv`, `stats.json` |

## 5. 모듈 구조 (✅ 구현 · ⏳ 골격만 · ⬜ 미착수)

```
config/
  treatments.yaml      시술 정의: 부위, 변화, mask_region, effect_levels, timeline
  variations.yaml      변주 축 · 모드 제약 · 가중치 · After 드리프트 · 출력 비율
  clinical_rig.yaml    임상 촬영 리그 고정 프로파일 + 정렬 임계값
  effects.yaml         효과 강도·경과 시점 문구
  postprocess.yaml     화소 축별 카메라 아티팩트 파라미터
  pricing.yaml         프로바이더 단가 (키 수령 후 갱신)
  samples_index.yaml   참조 이미지 태그 색인
  prompts/             before / identity_lock / after_clinical / after_selfie / mode_extra
  qa_checklist.yaml    비전 채점 항목 · hard_fail
  brand/onlif.json     브랜드 DB (갤러리 톤용)
src/bna/
  spec.py         ✅  프롬프트 조립 (인물 11축, 리그, 드리프트, 효과·시점)
  planner.py      ✅  가중 균형 샘플링, 축 고정
  postprocess.py  ✅  카메라 아티팩트 (테스트 완료)
  refs.py         ✅  참조 이미지 선택 (라이브러리 채우면 동작)
  version.py      ✅  프롬프트 버전 (git + config 해시)
  stats.py        ✅  통과율 통계, manifest
  batch.py        ✅  워커 풀·재시도·이어하기·비용 추정 (프로바이더 구현되면 동작) + 단계별 progress 기록
  progress.py     ✅  progress.json 기록·요약 (대시보드 실시간 패널용)
  queue.py        ✅  배치 큐 (queue.json, 순차 러너, 일시정지·순서·취소). 정지 조건(target_pass·cost_cap)은 batch.py
  qa/landmarks.py ⏳  MediaPipe 랜드마크, 부위 폴리곤(초안), 마스크, 합성 — 폴리곤 시각 확인 필요
  qa/structure.py ⏳  정렬·비율·밝기·프레임 검사 — 임계값 캘리브레이션 필요
  qa/identity.py  ⏳  ArcFace 게이트 — 임계값 캘리브레이션 필요
  qa/dedup.py     ⏳  임베딩 레지스트리
  qa/vision.py    ⏳  채점 규칙 (프로바이더 qa 구현 대기)
  providers/      ⏳  base(인터페이스·어댑터 훅) / gemini / openai_img / higgsfield — 키 수령 후 구현
  cli.py          ✅  --plan / --dry-run / --estimate / --run
  api.py          ✅  로컬 대시보드 서버 (stdlib HTTP): 큐·진행·목록·리뷰·라이브러리·내보내기(zip+manifest)·데모/시뮬레이션
web/index.html    ✅  대시보드: 생성(대기열·진행·미리보기) / 작업(목록→상세·검수) / 라이브러리(선택작 모음·내보내기). Supabase·팀 계정은 미착수
samples/reference/{clinical,selfie}/   참조 실사 라이브러리 (비어 있음)
outputs/{batch_id}/  결과 · manifest.csv · stats.json · state.json (git 제외)
```

## 6. 프로바이더 인터페이스
```python
class Provider:
    name: str
    concurrency: int
    def edit(image, prompt, mask=None) -> Image      # 임상: 원본 보존 우선
    def generate(prompt, aspect, ref=None) -> Image   # 셀카 After: ref=Before (인물 참조)
    def qa(before, after, checklist) -> dict         # {item: 0-10, notes}
```
역할 가설: Before = Higgsfield 또는 Gemini · After 편집 = Gemini · 채점 = Gemini/GPT. 스파이크로 확정.

## 7. 데이터 스키마
```
batch: batch_id, treatment, mode, target_pass, planned, started_at, finished_at, stats
item:  item_id, batch_id, variation{축}, before_prompt, after_prompt,
       provider{gen, edit, qa}, attempt, structure{align_err, face_ratio, luma_diff},
       scores{7항목}, dedup_group, passed, reviewer_pick, cost, created_at
```

## 8. 로드맵

| 단계 | 기간 | 산출 | 검증 |
|---|---|---|---|
| **0. 스파이크** | 키 수령 후 3일 | 팔자 · 임상+셀카 · 모델 3종 × 10장 | 편집 보존력(정렬 오차), 블라인드 구분율 |
| **1. 코어 파이프라인** | 1주 | CLI 배치: 생성→편집→3단 검수→정리 | 팔자·엠보 통과율 60% |
| **2. 대량화** | 1주 | 병렬·재시도·이어하기·비용 산출 | 시간당 통과작 100장 |
| **3. 시술 확장** | 1주 | 나머지 6개 시술 스펙 튜닝 | 시술별 통과율 표 |
| **4. UI·배포** | 1~2주 | 배치 요청 화면, 갤러리, Supabase 저장, 팀 계정 | BX·그로스 자체 실행 |

## 9. 확정
- 결과 비율 4:5
- 축 가중치: 한국 5:1:1:1:1, 여성 3:1, 연령 20대 후반~40대 중심 (`config/variations.yaml` weights)

## 10. 미결정
0. 사용 정책·지시문 검토: 현재 전부 오픈. 법무 가이드·의료진 검토는 추후 (`docs/usage-policy.md`)
2. 정렬 오차 임계값 (초안 2%)과 비전 채점 임계값(7/10)의 비용 균형
3. 셀카 After의 인물 참조 생성 지원 여부(모델별)와 동일성 유지력 → 스파이크 최우선 검증
4. 광고 심의상 생성 이미지 표기 방식
