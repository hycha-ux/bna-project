# 파이프라인 설계 (초안)

```
[요청] treatment + mode + count
   │
   ▼
[1. 변주 샘플링]  config/variations.yaml 에서 축 조합 무작위 추출 → persona/scene 스펙
   │
   ▼
[2. 프롬프트 조립]  config/prompts/*.md 템플릿 + treatments.yaml 의 시술별 변화 규칙
   │                Before 프롬프트 / After 프롬프트 (부위 외 요소는 문자 그대로 동일)
   ▼
[3. 생성]  Before 이미지 생성 → 그 이미지를 레퍼런스로 After 편집 생성 (동일성 확보)
   │        모델 후보: Gemini(이미지 편집·일관성) / GPT Image / Higgsfield(리얼 인물)
   ▼
[4. 자동 검수]  비전 모델로 체크리스트 채점 (손가락, 피부 텍스처, 머리카락, 동일성, 부위 외 변화)
   │             임계 미달 → 재생성 (최대 N회)
   ▼
[5. 저장]  outputs/{treatment}/{mode}/{id}_before.jpg, _after.jpg, meta.json (사용 변주·프롬프트·점수)
```

## 모델 역할 분담 (키 수령 후 검증)
| 단계 | 1안 | 2안 |
|---|---|---|
| Before 생성 | Higgsfield (리얼 인물) | Gemini image |
| After 편집 | Gemini (이미지 입력 기반 국소 편집) | GPT Image edit |
| 검수 | Gemini / GPT vision | — |

핵심 원칙: **After는 새로 그리지 않고 Before를 편집한다.** 인물 동일성과 구도 고정을 위해.

## 미결
- 시술별 "변화 강도" 표현 방식 (자연스러운 개선 범위 정의 필요 — 과장 금지)
- 모델별 리얼리티 비교 스파이크 (키 수령 후 각 모델로 팔자 셀카 10장씩)
- 최종 산출물 규격 (SNS 비율, 좌우 합성 여부, 워터마크)
