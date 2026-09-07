# 시스템 설계

## 전체 흐름

```
┌─ UI (prompf 위저드 계승) ─────────────────────────────┐
│ 1 시술  2 모드  3 변주(자동/수동)  4 미리보기  5 생성  │
└──────────────────────┬────────────────────────────────┘
                       │ POST /jobs {treatment, mode, count, overrides}
┌─ API 서버 (FastAPI) ─▼────────────────────────────────┐
│ 잡 큐 · 상태 · 히스토리 · 갤러리 조회                    │
└──────────────────────┬────────────────────────────────┘
┌─ 파이프라인 (src/bna) ▼───────────────────────────────┐
│ ① 변주 샘플링   config/variations.yaml + mode_rules    │
│ ② 프롬프트 조립  레이어 합성 (아래 표)                   │
│ ③ Before 생성   provider.generate                      │
│ ④ After 편집    provider.edit(before, after_prompt)     │
│ ⑤ 자동 검수     provider.qa → 7항목 점수               │
│ ⑥ 판정         threshold 미달 → ③부터 재시도 (max 3)    │
│ ⑦ 저장         이미지 + meta.json + 점수               │
└──────────────────────┬────────────────────────────────┘
┌─ 저장소 ──────────────▼───────────────────────────────┐
│ PoC: 로컬 outputs/  →  운영: Supabase Storage + DB      │
└───────────────────────────────────────────────────────┘
```

## 프롬프트 레이어 (prompf 공식을 B&A용으로 재정의)

| 순서 | 레이어 | prompf | B&A |
|---|---|---|---|
| 1 | 피사체 | korean model 고정 | 나라·연령·성별 변주 |
| 2 | 구도·각도 | 샷/앵글 (화보용) | 임상: 정면/반측/측면 고정 · 셀카: 하이/로우앵글 |
| 3 | 장면 | 스튜디오 배경 | 임상: 클리닉 벽 · 셀카: 생활 배경 6종 |
| 4 | 조명 | 브랜드 허용 풀 (버터플라이 등) | 임상: 링/창가 · 셀카: 형광등·야간·역광 포함 |
| 5 | 카메라 | full-frame 85mm, shallow DoF | 폰 카메라 화소·노이즈·기본 색보정 |
| 6 | 피부·리얼리티 | glass skin, dewy 이펙트 | 모공·솜털·잡티 **유지**, 리터칭 금지 |
| 7 | 모드 지시 | — | 임상 문서 스타일 / 셀카 손·폰 규칙 |
| 8 | 품질 접미 | 8K hyperrealistic | **제거** (AI 티 유발) |
| 9 | 브랜드 톤 | prompt_base | 후처리 색감에만 약하게 반영 (사진 자체엔 미적용) |
| — | After 편집 | 없음 | 시술별 after_change + "그 외 절대 변경 금지" |

## 모듈 구조

```
config/
  treatments.yaml      시술 정의 (부위, 변화, 허용 각도)
  variations.yaml      변주 축 + 모드별 제약
  prompts/             before.md / after.md / mode_extra.yaml
  qa_checklist.yaml    검수 항목·임계값
  brand/onlif.json     prompf 브랜드 DB 이관 (후처리·갤러리 톤용)
src/bna/
  spec.py              변주 샘플링, 프롬프트 조립  ← 구현됨 (dry-run 동작)
  providers/           gemini.py / openai.py / higgsfield.py (generate · edit · qa 인터페이스)
  pipeline.py          ③~⑦ 오케스트레이션, 재시도
  store.py             저장·히스토리 (로컬 → Supabase 교체 가능)
  api.py               FastAPI
web/
  index.html           prompf 위저드 UI 이식 (Vanilla JS 유지)
outputs/               결과 (git 제외)
```

## 프로바이더 인터페이스
```python
class Provider:
    def generate(prompt: str, aspect: str) -> Image
    def edit(image: Image, prompt: str) -> Image          # 국소 편집, 원본 보존 우선
    def qa(before: Image, after: Image, checklist) -> dict  # {item: score 0-10, notes}
```
모델별 역할은 스파이크로 결정. 가설: Before=Higgsfield 또는 Gemini, After 편집=Gemini, 검수=Gemini/GPT.

## 데이터 스키마 (meta.json → 운영 시 DB 테이블)
```
job_id, treatment, mode, variation{8축}, before_prompt, after_prompt,
provider{gen, edit, qa}, attempts, scores{7항목}, passed, reviewer_ok(사람), created_at
```

## 단계별 로드맵

| 단계 | 기간 | 산출 |
|---|---|---|
| **0. 스파이크** | 키 수령 후 2~3일 | 팔자 셀카 10장 × 모델 3종 → 리얼리티·편집 보존력 비교표, 모델 역할 확정 |
| **1. 파이프라인** | 1주 | CLI로 팔자·엠보 2개 시술 end-to-end (생성→편집→검수→저장) |
| **2. UI** | 1주 | prompf 위저드 이식 + 생성 버튼 + 갤러리 + 히스토리 |
| **3. 시술 확장** | 1주 | 나머지 6개 시술 스펙 튜닝, 통과율 측정 |
| **4. 팀 배포** | 1주 | Supabase 저장·권한, BX/그로스 계정 접근, 슬랙 알림 |

## 미결정 사항
1. 이미지 규격: 세로 4:5 / 9:16 / 1:1 중 기본값
2. 손 포함 셀카를 기본으로 할지 옵션으로 할지 (손가락 실패율에 따라)
3. 검수 임계값(현재 7/10)과 재시도 상한(3회)의 비용 균형
4. 광고 심의상 "생성 이미지" 표기 방식
