"""출발 간격(_StartGate) 실스레드 대역 검증 (2026-09-15 티모, API 0콜·$0).

selftest ㊱ 은 가짜 시계로 산술만 본다. 여기선 **진짜 OpenAIProvider 두 개**를 만들어
스레드 20개가 동시에 이미지 콜을 던질 때 ①두 인스턴스가 같은 문을 쓰나 ②출발 간격이 지켜지나
③채점(chat) 콜은 문을 안 지나나 ④동시 칸이 providers.yaml 값으로 읽히나를 센다.
requests.post 를 대역으로 바꿔 네트워크는 안 나간다. 간격은 빨리 끝나게 0.2초로 줄여 잰다(산식은 selftest).
"""
import os, sys, threading, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ["OPENAI_API_KEY"] = "stub-not-real"

import bna.providers.openai_img as oi


class _Resp:
    status_code, headers, text = 200, {}, ""

    def json(self):
        return {"data": [{"b64_json": ""}]}


starts, chat_starts, lock = [], [], threading.Lock()


def fake_post(url, **kw):
    with lock:
        (starts if "/images/" in url else chat_starts).append(time.monotonic())
    time.sleep(0.05)
    return _Resp()


oi.requests.post = fake_post
a, b = oi.OpenAIProvider(), oi.OpenAIProvider()
print("동시 칸(yaml)", a.concurrency, "· 문 공유", a.gate is b.gate, "· 설정 간격(초)", round(a.gate.interval, 2))
a.gate.interval = 0.2

ths = [threading.Thread(target=(a if i % 2 else b)._send, args=("/images/edits", [], {}, None)) for i in range(20)]
ths += [threading.Thread(target=a._send, args=("/chat/completions", None, None, {})) for _ in range(5)]
t0 = time.monotonic()
for t in ths:
    t.start()
for t in ths:
    t.join()
starts.sort()
gaps = [round(y - x, 3) for x, y in zip(starts, starts[1:])]
print("이미지 콜", len(starts), "· 최소 간격", min(gaps), "· 전체", round(starts[-1] - starts[0], 2), "초")
print("채점 콜", len(chat_starts), "· 첫 채점까지", round(min(chat_starts) - t0, 3), "초")
# ⚠ 최소 간격은 Windows 타이머 해상도(≈15.6ms)만큼 흔들린다 — 자리 예약은 정확해도 스레드가 깨어나
#   기록하는 순간이 늦거나 이르다(첫 실행 0.188초). 그래서 한 틱 여유 + **평균 간격**을 같이 본다.
avg = (starts[-1] - starts[0]) / (len(starts) - 1)
print("평균 간격", round(avg, 3))
ok = (a.concurrency == 10 and a.gate is b.gate and len(starts) == 20 and min(gaps) >= 0.2 - 0.02
      and avg >= 0.2 - 0.005 and max(chat_starts) - t0 < 0.5)
print("PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
