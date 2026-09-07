"""카메라 아티팩트 후처리 (A2). 순수 이미지 연산이라 키 없이 동작.
Before/After 세트에 같은 seed 로 적용해 동일 특성을 보장한다."""
import io, random
import numpy as np
from PIL import Image, ImageFilter, ImageEnhance
from .spec import load


def _profile(quality_key: str, mode: str) -> dict:
    p = load("postprocess.yaml")["profiles"]
    return p["clinical"] if mode == "clinical" else p.get(quality_key, p["mid"])


def apply(img: Image.Image, quality_key: str, mode: str, seed: int = 0) -> bytes:
    prof = _profile(quality_key, mode)
    rng = np.random.default_rng(seed)
    im = img.convert("RGB")
    arr = np.asarray(im).astype(np.float32)

    # 1. 약한 HDR 톤 (폰 카메라의 하이라이트 눌림·섀도 들어올림)
    t = prof["hdr_tone"]
    if t:
        x = arr / 255.0
        arr = (x + t * (np.sqrt(x) - x)) * 255.0

    # 2. 센서 노이즈 (휘도 + 약한 컬러 노이즈)
    s = prof["noise_sigma"]
    if s:
        luma = rng.normal(0, s, arr.shape[:2] + (1,))
        chroma = rng.normal(0, s * 0.4, arr.shape)
        arr = arr + luma + chroma

    # 3. 비네팅
    v = prof["vignette"]
    if v:
        h, w = arr.shape[:2]
        yy, xx = np.mgrid[0:h, 0:w]
        r = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2)
        arr = arr * (1 - v * np.clip(r, 0, 1) ** 2)[..., None]

    im = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))

    # 4. 미세 색수차 (R/B 채널 서브픽셀 시프트)
    c = prof["chroma_shift_px"]
    if c:
        r, g, b = im.split()
        r = r.transform(r.size, Image.AFFINE, (1, 0, c, 0, 1, 0), resample=Image.BILINEAR)
        b = b.transform(b.size, Image.AFFINE, (1, 0, -c, 0, 1, 0), resample=Image.BILINEAR)
        im = Image.merge("RGB", (r, g, b))

    # 5. 샤픈/소프트
    sh = prof["sharpen"]
    if sh > 0:
        im = ImageEnhance.Sharpness(im).enhance(1 + sh)
    elif sh < 0:
        im = im.filter(ImageFilter.GaussianBlur(radius=-sh * 2))

    # 6. JPEG 재압축 (압축 흔적)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=int(prof["jpeg_quality"]), subsampling=2)
    return buf.getvalue()
