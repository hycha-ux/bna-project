"""소스에 날것으로 박힌 제어문자(0x00·0x1f·0x7f)를 이스케이프 '글자'로 되돌린다.

왜: `\\x00` 같은 이스케이프가 파일을 쓰는 단계에서 해석돼 **진짜 제어문자 1바이트**로 들어가면,
정규식의 뜻은 같아 테스트가 통과하지만 git 이 그 파일을 **바이너리로 판정**한다
→ диff 가 안 보여 리뷰가 불가능하고, 두 사람이 같이 고치면 병합도 못 한다.
"""
import sys
from pathlib import Path

MAP = {b"\x00": rb"\x00", b"\x1f": rb"\x1f", b"\x7f": rb"\x7f"}


def main(paths):
    for p in paths:
        f = Path(p)
        b = f.read_bytes()
        found = {k: b.count(k) for k, _ in MAP.items()}
        if not any(found.values()):
            print(f"{p}: 날것 제어문자 없음")
            continue
        n = b
        for raw, esc in MAP.items():
            n = n.replace(raw, esc)
        f.write_bytes(n)
        print(f"{p}: {found} → 이스케이프 글자로 교체, {len(b)} → {len(n)} 바이트")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
