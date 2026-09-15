#!/usr/bin/env python3
"""위클리 브리핑 최종본 빌드 — 템플릿의 __IMG_*__ 자리표시자에 이미지를 base64로 심는다.

사용법:
    python3 inject.py <template.html> <mapping.json> <out.html>

mapping.json 예시 (자리표시자 → 이미지 파일 경로):
    {"__IMG_ADOPTED__": "thumb_adopted.jpg", "__IMG_PRICELIST__": "thumb_pricelist.jpg"}

규칙: 템플릿에 남은 자리표시자가 하나라도 있으면 실패한다(빈 이미지 배포 방지).
"""
import base64, json, mimetypes, pathlib, re, sys


def main(tpl_path, map_path, out_path):
    tpl = pathlib.Path(tpl_path).read_text()
    mapping = json.loads(pathlib.Path(map_path).read_text())
    for placeholder, img in mapping.items():
        assert placeholder in tpl, f"템플릿에 자리표시자 없음: {placeholder}"
        p = pathlib.Path(img)
        mime = mimetypes.guess_type(p.name)[0] or "image/jpeg"
        uri = f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()
        tpl = tpl.replace(placeholder, uri)
    leftovers = re.findall(r"__IMG_[A-Z_]+__", tpl)
    assert not leftovers, f"미치환 자리표시자 잔존: {leftovers}"
    pathlib.Path(out_path).write_text(tpl)
    print(f"OK {out_path} ({len(tpl)} bytes)")


if __name__ == "__main__":
    main(*sys.argv[1:4])
