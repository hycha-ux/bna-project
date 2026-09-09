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
import requests

from .base import Provider
from ..spec import load

API = "https://api.openai.com/v1"
TIMEOUT = 300


class OpenAIProvider(Provider):
    name, env_key, concurrency = "openai", "OPENAI_API_KEY", 3
    supports_mask, supports_ref, supports_style_refs = True, True, True

    def __init__(self):
        super().__init__()
        self.cfg = load("providers.yaml")["openai"]

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

    @staticmethod
    def _first_image(payload: dict) -> bytes:
        data = (payload.get("data") or [])
        if not data or "b64_json" not in data[0]:
            raise RuntimeError(f"이미지 없음: {json.dumps(payload)[:400]}")
        return base64.b64decode(data[0]["b64_json"])

    def _post(self, path, *, files=None, data=None, body=None, retry_without=()):
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
            for _, (_, stream, _) in (files or []):
                stream.seek(0)
            r = (requests.post(f"{API}{path}", headers=self._headers(False), files=files, data=data, timeout=TIMEOUT)
                 if files is not None else
                 requests.post(f"{API}{path}", headers=self._headers(True), json=body, timeout=TIMEOUT))
            if r.status_code < 400:
                return r.json()
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
        j = self._post("/chat/completions", body=body)
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
