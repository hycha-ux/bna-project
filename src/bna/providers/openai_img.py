"""OpenAI(GPT) 이미지 생성·편집·비전 채점.

2026-09-08 성연서님 확정으로 **셀카 모드의 기본 프로바이더**다
(근거: docs/selfie-prompt-v1-review-0908-teemo.md — 프레이밍 준수 GPT 4/4 vs Gemini 0/4).

SDK 를 안 쓰고 REST 를 직접 친다. 이미지 API 는 파라미터가 자주 늘고(예: input_fidelity)
SDK 버전이 낡으면 그 파라미터를 못 넘기는데, 그때 나는 오류가 "그 옵션이 없다"가 아니라
조용히 빠진 결과물이라 알아채기 어렵다.

모델·크기·품질 상수는 전부 config/providers.yaml 이 정본이다 — 여기에 리터럴로 박지 마라.
"""
import base64
import io
import json
import mimetypes
import threading
import time
import requests

from .base import Provider
from ..spec import load, ROOT

API = "https://api.openai.com/v1"
TIMEOUT = 300
# 429(한도)·5xx(일시 장애) 재시도 대기(초). 이미지 1콜이 실측 ~108초라 이 정도 기다림은 회차를 못 망친다 —
# 기다리지 않는 쪽이 비싸다(그 예외 하나가 배치 전체를 죽인다). 소진되면 종전대로 오류를 올린다.
RETRY_WAITS_S = (10, 30, 60)

# 분당 이미지 한도의 안전 여유 — 한도 8이면 7.2장/분(8.3초 간격)으로 출발시킨다.
GATE_SAFETY = 0.9


class _StartGate:
    """이미지 콜의 **출발 간격**을 지킨다 (2026-09-15 티모, 성연서님 "분당 이미지 수 8장").

    왜 필요한가: 동시 칸(concurrency)은 '들고 있는 콜 수'만 묶지 '분당 출발 수'는 안 묶는다.
    배치가 시작하는 순간 빈 칸 10개가 한꺼번에 채워지면 1초 안에 10콜이 나가 한도 8을 넘기고,
    429 재시도 3번이 소진되면 그 예외 하나가 배치 전체를 죽인다. 그래서 칸과 간격을 한 벌로 둔다.
    ⚠ 둘 중 하나만 끄지 마라 — 칸만 두면 버스트, 간격만 두면 느리다.

    ⚠ 프로세스 안에서만 지킨다. 큐는 배치를 한 번에 하나씩 돌려(queue._loop) 한 프로세스면 충분하지만,
      예약작업 유료 회차(ops/register-paid-run.ps1)를 서버 배치와 **동시에** 돌리면 두 프로세스가 각자 센다.
    429 재시도도 이 문을 다시 지난다(_send 루프 안) — 한도에 부딪힌 직후 또 몰려가지 않게."""

    def __init__(self, per_minute, clock=time.monotonic, sleep=time.sleep):
        self.interval = 60.0 / (per_minute * GATE_SAFETY) if per_minute else 0.0
        self._next, self._lock, self._clock, self._sleep = 0.0, threading.Lock(), clock, sleep

    def wait(self) -> float:
        """차례가 올 때까지 잔다. 잔 초를 돌려준다(회귀가 읽는다)."""
        if self.interval <= 0:
            return 0.0
        with self._lock:                                  # 자리 예약만 락 안에서 — 자는 건 락 밖(다른 콜 예약을 막지 않는다)
            now = self._clock()
            at = max(now, self._next)
            self._next = at + self.interval
        if at > now:
            self._sleep(at - now)
        return at - now


_GATE_LOCK = threading.Lock()
_IMAGE_GATE = None          # 프로세스 공용 — 인스턴스마다 만들면 인스턴스 수만큼 한도가 늘어난다

# 실청구 대조용 토큰 원장. config/pricing.yaml 의 호출당 단가는 **추정치**라
# ($0.19/장, 2026-09-08 미실측) 그 위에 선 "통과 1장 $2.68" 도 추정 위에 서 있다.
# API 응답의 usage 는 과금의 원장 그 자체이므로, 호출마다 한 줄씩 남겨 실단가를 사후에 잰다.
# 집계 = tools/usage_report.py. 쓰기 실패는 삼킨다 — 계측이 생성을 죽이면 안 된다.
_USAGE_LOCK = threading.Lock()
_USAGE_PATH = ROOT / "outputs" / "usage.jsonl"


class OpenAIProvider(Provider):
    name, env_key, concurrency = "openai", "OPENAI_API_KEY", 3
    supports_mask, supports_ref, supports_style_refs = True, True, True

    def __init__(self):
        super().__init__()
        global _IMAGE_GATE
        self.cfg = load("providers.yaml")["openai"]
        # 동시 칸·출발 간격의 정본은 providers.yaml 한 곳이다(2026-09-15). 값이 없으면 종전 3칸·간격 없음.
        self.concurrency = int(self.cfg.get("concurrency") or 3)
        with _GATE_LOCK:
            if _IMAGE_GATE is None:
                _IMAGE_GATE = _StartGate(self.cfg.get("images_per_minute"))
        self.gate = _IMAGE_GATE

    # --- 공통 ---
    def _headers(self, json_body: bool):
        h = {"Authorization": f"Bearer {self.key}"}
        if json_body:
            h["Content-Type"] = "application/json"
        return h

    def _fidelity(self) -> dict:
        """input_fidelity 는 모델이 지원할 때만 보낸다.
        ⚠ 2026-09-08 실측: gpt-image-2 는 **미지원**이다(400 invalid_input_fidelity_model).
          gpt-image-1 계열로 돌아갈 때를 위해 설정 키는 남겨 뒀다 — providers.yaml 에서 값을 주면 보낸다."""
        v = self.cfg.get("input_fidelity")
        return {"input_fidelity": v} if v else {}

    def _size(self, aspect: str) -> str:
        sizes = self.cfg["aspect_size"]
        if aspect not in sizes:
            # 조용히 다른 비율로 내보내지 않는다 — 세트 안에서 비율이 갈리면 전후 비교가 깨진다.
            raise ValueError(f"지원하지 않는 aspect: {aspect} (providers.yaml aspect_size 에 추가해라)")
        return sizes[aspect]

    def _log_usage(self, path, payload, extra):
        u = (payload or {}).get("usage")
        if not u:
            return
        rec = {"at": round(time.time(), 3), "path": path, "usage": u, **extra}
        try:
            with _USAGE_LOCK:
                _USAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
                with open(_USAGE_PATH, "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + chr(10))
        except Exception:
            pass

    @staticmethod
    def _first_image(payload: dict) -> bytes:
        data = (payload.get("data") or [])
        if not data or "b64_json" not in data[0]:
            raise RuntimeError(f"이미지 없음: {json.dumps(payload)[:400]}")
        return base64.b64decode(data[0]["b64_json"])

    def _send(self, path, files, data, body):
        """한 번 보낸다. **429(한도)·5xx(일시 장애)는 여기서 기다렸다 다시 보낸다** (2026-09-15 티모).

        왜 필요한가: 종전엔 429 든 500 이든 `_post` 가 그 자리에서 RuntimeError 를 올렸고, 그 예외는
        run_item → run() 의 gather 로 올라가 **배치 전체를 죽였다**. 재시도가 아예 없었다.
        시점별 After 를 동시에 던지기 시작하면(2026-09-15 초안) 같은 순간에 같은 엔드포인트로 3콜이
        착지하므로, 한도에 스치는 확률이 0 이 아니다 — 완화(병렬)와 방어(재시도)는 한 벌이다.
        ⚠ 둘 중 하나만 끄지 마라.

        ⚠ 재시도 전에 파일 스트림을 되감아야 한다. requests 가 첫 요청에서 BytesIO 를 끝까지 읽어
          두 번째엔 **0바이트**가 나가고, API 는 그걸 'invalid_image_file' 로 답한다
          (2026-09-08 실측). 그래서 되감기는 이 함수 맨 앞에 있다 — 재시도 경로가 둘이라 한 곳에 둔다.
        """
        for i in range(len(RETRY_WAITS_S) + 1):
            for _, (_, stream, _) in (files or []):
                stream.seek(0)
            if path.startswith("/images/"):              # 출발 간격 — 채점(chat)은 한도 버킷이 달라 안 태운다
                self.gate.wait()
            r = (requests.post(f"{API}{path}", headers=self._headers(False), files=files, data=data, timeout=TIMEOUT)
                 if files is not None else
                 requests.post(f"{API}{path}", headers=self._headers(True), json=body, timeout=TIMEOUT))
            if not (r.status_code == 429 or r.status_code >= 500) or i >= len(RETRY_WAITS_S):
                return r
            # 서버가 알려 준 대기 시간이 있으면 그걸 따른다(우리 값보다 길 수 있다).
            try:
                wait = max(float(r.headers.get("retry-after") or 0), RETRY_WAITS_S[i])
            except ValueError:
                wait = RETRY_WAITS_S[i]
            print(f"[openai] {path} HTTP {r.status_code} → {wait:.0f}초 뒤 재시도 ({i + 1}/{len(RETRY_WAITS_S)})", flush=True)
            time.sleep(min(wait, 120))
        return r

    def _post(self, path, *, files=None, data=None, body=None, retry_without=(), extra=None):
        """400 이 '모르는 파라미터' 때문이면 그 파라미터를 빼고 재시도한다(fail-open).
        API 가 옵션을 늘리거나 줄여도 파이프라인 전체가 멈추지는 않게.

        ⚠ 재시도 전에 파일 스트림을 되감아야 한다. requests 가 첫 요청에서 BytesIO 를 끝까지 읽어
          두 번째엔 **0바이트**가 나가고, API 는 그걸 'invalid_image_file' 로 답한다 —
          즉 진짜 원인(모르는 파라미터)이 엉뚱한 오류로 둔갑한다 (2026-09-08 실측, 첫 실집행에서 물림).
        """
        for drop in (None,) + tuple(retry_without):
            if drop is not None:
                if data is not None:
                    data = {k: v for k, v in data.items() if k != drop}
                if body is not None:
                    body = {k: v for k, v in body.items() if k != drop}
            r = self._send(path, files, data, body)
            if r.status_code < 400:
                j = r.json()
                self._log_usage(path, j, {
                    "model": (body or data or {}).get("model"),
                    "size": (body or data or {}).get("size"),
                    "quality": (body or data or {}).get("quality"),
                    "refs": len(files or []) if files is not None else 0,
                    **(extra or {}),
                })
                return j
            msg = r.text[:400]
            if not (r.status_code == 400 and drop is None and retry_without):
                raise RuntimeError(f"OpenAI {path} HTTP {r.status_code}: {msg}")
        raise RuntimeError(f"OpenAI {path} 실패: {msg}")

    @staticmethod
    def _part(name, blob, i=0):
        kind = "image/png" if blob[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
        ext = mimetypes.guess_extension(kind) or ".png"
        return (name, (f"{name}{i}{ext}", io.BytesIO(blob), kind))

    # --- 생성 ---
    def generate(self, prompt, aspect, ref=None, style_refs=None, seed=None) -> bytes:
        refs = ([ref] if ref else []) + list(style_refs or [])
        if refs:
            # 인물 참조가 있으면 generations 가 아니라 edits 다 — 참조 이미지를 받는 쪽이 여기다.
            files = [self._part("image[]", b, i) for i, b in enumerate(refs)]
            data = {"model": self.cfg["image_model"], "prompt": prompt, "size": self._size(aspect),
                    "quality": self.cfg["quality"], "n": "1", **self._fidelity()}
            return self._first_image(self._post("/images/edits", files=files, data=data,
                                                retry_without=("input_fidelity",)))
        body = {"model": self.cfg["image_model"], "prompt": prompt, "size": self._size(aspect),
                "quality": self.cfg["quality"], "n": 1}
        return self._first_image(self._post("/images/generations", body=body))

    # --- 편집 (마스크) ---
    def edit(self, image, prompt, mask=None) -> bytes:
        files = [self._part("image[]", image)]
        if mask:
            files.append(self._part("mask", mask))
        data = {"model": self.cfg["image_model"], "prompt": prompt,
                "quality": self.cfg["quality"], "n": "1", **self._fidelity()}
        return self._first_image(self._post("/images/edits", files=files, data=data,
                                            retry_without=("input_fidelity",)))

    # --- 비전 채점 ---
    def qa(self, before, after, items, mode) -> dict:
        keys = list(items)
        rules = "\n".join(f"- {k}: {v}" for k, v in items.items())
        prompt = (
            f"You are grading a generated before/after photo pair for a clinic ({mode} mode).\n"
            f"Image 1 = BEFORE, image 2 = AFTER.\n"
            f"Score each item 0-10 (10 = perfect). Be strict; when in doubt score low.\n"
            'If an item explicitly says it may not apply and the thing it grades is absent from both images, '
            'reply "n/a" as the score for that item instead of a number. Never score an absent subject 0.\n'
            f"{rules}\n\n"
            'Reply with JSON only: {"item_key": {"score": 0-10 or "n/a", "note": "short reason"}} for exactly these keys: '
            + ", ".join(keys)
        )
        content = [{"type": "text", "text": prompt}]
        for b in (before, after):
            content.append({"type": "image_url",
                            "image_url": {"url": "data:image/png;base64," + base64.b64encode(b).decode()}})
        body = {"model": self.cfg["vision_model"], "messages": [{"role": "user", "content": content}],
                "response_format": {"type": "json_object"}}
        j = self._post("/chat/completions", body=body, extra={"purpose": "qa"})
        raw = json.loads(j["choices"][0]["message"]["content"])
        # 모델이 항목을 빠뜨리면 0 으로 채우지 마라 — 0 은 '나쁨'이고 누락은 '못 잼'이다.
        # 못 잰 항목은 임계 미달로 떨어뜨려 재시도시키되, note 에 이유를 남긴다.
        out = {}
        for k in keys:
            v = raw.get(k)
            s = v.get("score") if isinstance(v, dict) else None
            if isinstance(s, bool):                       # True/False 는 점수가 아니다
                s = None
            if isinstance(s, (int, float)):
                out[k] = {"score": float(s), "note": str(v.get("note", ""))[:200]}
            elif isinstance(s, str) and s.strip().lower() in ("n/a", "na", "not applicable", "none"):
                # '해당 없음' 은 0점이 아니다 — 없는 걸 못 그렸다고 탈락시키면 그 항목은 영영 통과 못 한다
                out[k] = {"score": None, "note": str(v.get("note", ""))[:200] or "해당 없음(이 사진엔 없다)"}
            else:
                out[k] = {"score": 0.0, "note": "채점 누락 — 모델이 이 항목을 안 냈다(미측정)"}
        return out

    # --- 범용 JSON 응답 (검수 채점 외의 텍스트 판단용) ---
    def chat_json(self, prompt: str, images=(), *, purpose: str = "chat", model: str = None) -> dict:
        """텍스트(+이미지) → JSON 한 덩이. qa() 와 같은 모델·같은 원장을 쓴다.

        ⚠ `purpose` 를 반드시 다르게 준다 — usage.jsonl 은 모델 이름으로 접히는데,
          검수(qa)와 다른 용도가 한 칸에 섞이면 "검수 1회 $0.0042" 같은 **실측 단가가 조용히 흐려진다**
          (그 값이 지금 회차 예산의 근거다). 원장에 purpose 를 같이 적어 칸을 가른다.
        """
        content = [{"type": "text", "text": prompt}]
        for b in images or ():
            kind = "image/png" if b[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
            content.append({"type": "image_url",
                            "image_url": {"url": f"data:{kind};base64," + base64.b64encode(b).decode()}})
        body = {"model": model or self.cfg["vision_model"],
                "messages": [{"role": "user", "content": content}],
                "response_format": {"type": "json_object"}}
        j = self._post("/chat/completions", body=body, extra={"purpose": purpose})
        return {"data": json.loads(j["choices"][0]["message"]["content"]),
                "usage": j.get("usage") or {}, "model": body["model"]}
