"""OpenAI 이미지 한도(분당 요청·이미지)를 응답 헤더로 읽는다 (2026-09-15 티모, 빌디 제안 1번 검토).

빌디는 "한도 확인은 대시보드에서만 된다"고 했지만, API 응답 헤더 `x-ratelimit-*` 가 그 값을 직접 준다.
가장 싼 호출(quality=low, 1024x1024, generations) 1회로 헤더만 찍는다. 이미지는 저장하지 않는다.
키 값은 출력하지 않는다.
"""
import os, sys, time
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
# 생성 서버와 같은 금고를 읽는다(ops/gen-poller.mjs 가 이 파일에서 자식 환경을 채운다). 값은 출력하지 않는다.
VAULT = Path(os.environ.get("TEEMO_KEYS", r"C:\Users\medib\teemo\keys.env"))
key = os.getenv("OPENAI_API_KEY", "")
if not key and VAULT.exists():
    for line in VAULT.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("OPENAI_API_KEY="):
            key = s.split("=", 1)[1].strip().strip('"').strip("'")
if not key:
    sys.exit("OPENAI_API_KEY 없음")

import yaml
cfg = yaml.safe_load((ROOT / "config" / "providers.yaml").read_text(encoding="utf-8"))["openai"]
body = {"model": cfg["image_model"], "prompt": "a plain white ceramic cup on a table", "size": "1024x1024",
        "quality": "low", "n": 1}
t0 = time.time()
r = requests.post("https://api.openai.com/v1/images/generations", headers={"Authorization": f"Bearer {key}"},
                  json=body, timeout=300)
print("model", cfg["image_model"], "HTTP", r.status_code, "sec", round(time.time() - t0, 1))
for k, v in r.headers.items():
    if k.lower().startswith("x-ratelimit") or k.lower() in ("openai-processing-ms", "retry-after"):
        print(k, "=", v)
if r.status_code < 400:
    print("usage", (r.json() or {}).get("usage"))
else:
    print(r.text[:300])
