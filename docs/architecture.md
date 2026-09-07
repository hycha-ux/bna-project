# 시스템 설계 (v2)

브리프의 세 축(실사 클로즈업 · 임상 동일 조건 · 대량생산)을 구조로 보장하는 설계.

## 1. 전체 흐름

```
[배치 요청]  시술 · 모드 · 목표 통과 수 · (옵션) 축 고정
     │
     ▼
[플래너]     라틴 방격 샘플링으로 변주 조합 N개 생성 (중복 없음, 축 고르게 분포)
     │       예상 호출 수·비용 산출 → 시작 확인
     ▼
[워커 풀]    조합마다 아래를 병렬 실행 (동시 N건)
     │   ① 프롬프트 조립 (레이어 합성)
     │   ② Before 생성            provider.generate
     │   ③ After 편집              provider.edit(before, after_prompt)   ← 새로 그리지 않음
     │   ④ 자동 검수 (3단)
     │        a. 구조 검사: 얼굴 검출 · 랜드마크 정렬 오차 · 시술 부위 프레임 내 포함 여부
     │        b. 비전 채점: 7항목 0~10 (손·피부·머리카락·동일성·드리프트·효과·AI티)
     │        c. 중복 검사: 얼굴 임베딩으로 배치 내 유사 인물 제거
     │   ⑤ 판정: 미달 → ②부터 최대 3회 재시도
     ▼
[정리]       파일명 규칙 적용 · 배치 폴더 · manifest.csv · 통계(통과율, 호출/통과)
     ▼
[갤러리]     통과작만 노출. 사람은 여기서 최종 픽 (선택)
```

## 2. 프롬프트 레이어

| 순서 | 레이어 | 임상 모드 | 셀카 모드 |
|---|---|---|---|
| 1 | 인물 | 나라·연령·성별 + 얼굴형·피부톤 세부 | 동일 |
| 2 | 프레이밍 | 얼굴 클로즈업 계열, 세부 구도 자유 (규격 미고정) | 동일 |
| 3 | 촬영 리그 | **`clinical_rig.yaml` 고정 세트** (카메라·거리·조명·배경·자세) | 배경·각도·조명·화소 변주 |
| 4 | 피부·리얼리티 | 모공·솜털·잡티 유지, 리터칭 금지 | 동일 + 폰 카메라 처리 특성 |
| 5 | 모드 지시 | 무표정·머리 묶음·노메이크업·헤어밴드·가운 | 자연 표정, 손 없는 구도 기본 |
| 6 | 금지 | 화보 접미, 뷰티 필터, 대칭, 스튜디오 보케 | 동일 |
| — | After 편집 | 시술별 `after_change` + 그 외 변경 금지 | 동일 |

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
| 샘플링 | `planner.py`: 축별 옵션을 라틴 방격으로 배분. 배치 내 조합 중복 0 |
| 병렬 | `asyncio` 워커 풀, 프로바이더별 동시성 상한·레이트리밋 준수 |
| 재시도 | 조합 단위 최대 3회. 실패 조합은 `failed.csv`에 사유와 함께 기록 |
| 비용 | 프로바이더별 단가표(`config/pricing.yaml`) × 예상 호출 수. 통과율 이력으로 보정 |
| 이어하기 | 배치 상태를 `state.json`에 저장. 중단 후 재실행 시 미완료 조합만 처리 |
| 정리 | `{treatment}_{mode}_{country}{age}{gender}_{id}_{before|after}.jpg`, `manifest.csv`, `stats.json` |

## 5. 모듈 구조

```
config/
  treatments.yaml      시술 정의: 부위, 변화, 허용 각도
  variations.yaml      변주 축 + 모드별 제약
  clinical_rig.yaml    임상 촬영 리그 고정 프로파일
  prompts/             before.md / after.md / mode_extra.yaml
  qa_checklist.yaml    비전 채점 항목 · 구조 검사 임계값
  pricing.yaml         프로바이더 단가
  brand/onlif.json     브랜드 DB (갤러리 톤용)
src/bna/
  spec.py              프롬프트 조립                       ← 구현됨
  planner.py           라틴 방격 샘플링, 비용 산출
  providers/           gemini / openai / higgsfield (generate · edit · qa)
  qa/                  structure.py (랜드마크·정렬) · vision.py (채점) · dedup.py (임베딩)
  batch.py             워커 풀, 재시도, 상태 저장, 정리
  cli.py               배치 실행 진입점
  api.py               UI용 FastAPI (2단계)
web/                   UI 신규 설계 (2단계)
outputs/{batch_id}/    결과 (git 제외)
```

## 6. 프로바이더 인터페이스
```python
class Provider:
    name: str
    concurrency: int
    def generate(prompt, aspect, seed=None) -> Image
    def edit(image, prompt, mask=None) -> Image      # 원본 보존 우선
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

## 9. 미결정
1. 라틴 방격 축 우선순위 (모든 축 균등 vs 나라·연령 우선)
2. 정렬 오차 임계값 (초안 2%)과 비전 채점 임계값(7/10)의 비용 균형
3. 마스크 편집 지원 모델 유무에 따른 After 생성 방식 분기
4. 광고 심의상 생성 이미지 표기 방식
