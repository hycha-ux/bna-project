# B&A Project — 온리프 시술 전후(Before & After) 이미지 자동 생성

온리프 성형외과 시술별 B&A 이미지를 AI로 자동 생성하는 파이프라인.
리얼리티가 핵심이며, **후기용(임상)**과 **셀카용(일반인)** 두 가지 모드로 출력한다.

## 문서
- [요구사항](docs/requirements.md) — 시술 목록, 모드, 변주 축, 품질 기준
- [프로젝트 브리프](docs/brief.md) — 목적, 전작(prompf) 대비 강화 포인트, 범위, 성공 기준
- [시스템 설계](docs/architecture.md) — 흐름, 프롬프트 레이어, 모듈, 로드맵
- [설계 검토](docs/gap-review.md) — 목표 달성을 위해 추가할 것 (우선순위)
- [목표 점검·도구 판정](docs/gap-check-0907-teemo.md) — 빈 곳 점검(2026-09-07) + MediaPipe·InsightFace 필요성 실측
- [카테고리별 프롬프트 설계 방안](docs/prompt-design-0907-teemo.md) — 셀카용 4칸 설계 + 임상용 전환 규칙 (2026-09-07)
- [언어 A/B 실측·팔자 우선 설계](docs/lang-ab-0907-teemo.md) — 영문 vs 한글 36장 비교, 페르소나형 before_condition, 팔자 마스크 교정 (2026-09-07)
- [셀카 프롬프트 1차 확정](docs/selfie-prompt-v1-0908-buildy.md) — 프레이밍·맥락 축, 시점별 After 드리프트(직후=병원), 피부 상태 잠금, Before 강도 3단계, 드리프트 버그 수정 (2026-09-08)
- [KOS 이미지 수급 검토](docs/kos-image-review-0907-teemo.md) — 실제 고객 사진을 쓸 수 있나(권리·기술·설계 3층, 2026-09-07 검토 전용)
- [사용 정책](docs/usage-policy.md) — 임시: 전부 오픈, 법무 가이드 추후
- [파이프라인 초안](docs/pipeline.md) — 생성 단계 상세
- [임상 촬영 리그](config/clinical_rig.yaml) — 후기용 고정 촬영 조건·정렬 임계값
- [시술 정의](config/treatments.yaml) — 시술별 변화 포인트와 프롬프트 규칙
- [변주 축](config/variations.yaml) — 나라/연령/성별/배경/각도/조명/색감/화소

## 구조
```
config/          시술·변주·프롬프트 설정 (코드가 아닌 데이터)
src/bna/         생성 파이프라인 (프롬프트 조립 → 생성 → 검수 → 저장)
src/bna/api.py   로컬 대시보드 서버 (표준 라이브러리, 의존성 없음)
web/             대시보드 화면 (단일 HTML)
samples/reference/  실제 참고 B&A 이미지 (구도·톤 레퍼런스)
outputs/         생성 결과 (git 제외)
```

## 시작
```bash
cp .env.example .env   # 키 입력
python3 -m src.bna.cli --treatment nasolabial --mode selfie --count 100 --plan          # 변주 분포 확인
python3 -m src.bna.cli --treatment nasolabial --mode selfie --count 4 --dry-run       # 프롬프트만
python3 -m src.bna.cli --treatment nasolabial --mode clinical --count 30 --fix country=korea --fix gender=female --estimate  # 비용 추정
python3 -m src.bna.cli --treatment nasolabial --mode selfie --count 50 --run                     # 실제 배치 (키 필요)
```

## 대시보드 (로컬)
```bash
PYTHONPATH=src python3 -m bna.api          # http://localhost:8765 자동 오픈
PYTHONPATH=src python3 -m bna.api --demo   # 키 없이 화면 확인용 데모 배치(자리표시 이미지) 생성 후 실행
```
- **배치 요청**: 시술·모드·수량·시드·축 고정 → 변주 분포 / 프롬프트 미리보기 / 비용 추정 / 프롬프트 배치 저장 / 실제 실행(키 필요)
- **배치 목록**: `outputs/` 아래 배치별 통과율·시도/통과·$/통과·리뷰 현황
- **갤러리·리뷰**: Before/After 쌍, 자동검수 결과·축별 통과율, 사람 리뷰(선택/반려 + 불합격 사유 태그 + 메모) → `outputs/<batch>/<item>/review.json`

