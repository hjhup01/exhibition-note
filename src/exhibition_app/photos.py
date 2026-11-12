"""관람 사진: 올린 이미지를 검사하고 알맞은 크기의 JPEG로 바꾼다. 기록에는 사진 ID 목록만 둔다.

- 받는 형식: JPG·PNG·WEBP (휴대폰 사진은 브라우저가 보통 JPG로 올린다)
- 원본은 MAX_UPLOAD_BYTES 이하, 전시당 MAX_PHOTOS장까지
- 긴 변을 MAX_SIDE px로 줄이고 휴대폰 회전 정보(EXIF)를 반영해 JPEG로 저장한다(위치 등 EXIF 정보는 버린다)
"""
import io
import json

from . import messages

MAX_PHOTOS = 3
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_SIDE = 1600
JPEG_QUALITY = 85
ACCEPTED_TYPES = ["jpg", "jpeg", "png", "webp"]
MIME = "image/jpeg"


class PhotoError(Exception):
    """str()은 화면에 그대로 보여 줄 한국어 문구."""


def prepare_image(data):
    """올린 파일(bytes) → 줄인 JPEG bytes. 이미지가 아니거나 너무 크면 PhotoError."""
    if not data:
        raise PhotoError(messages.PHOTO_INVALID)
    if len(data) > MAX_UPLOAD_BYTES:
        raise PhotoError(messages.PHOTO_TOO_LARGE)
    from PIL import Image, ImageOps, UnidentifiedImageError
    try:
        with Image.open(io.BytesIO(data)) as img:
            img = ImageOps.exif_transpose(img)  # 휴대폰에서 찍은 방향대로 세운다
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            img.thumbnail((MAX_SIDE, MAX_SIDE))
            out = io.BytesIO()
            img.save(out, "JPEG", quality=JPEG_QUALITY, optimize=True)  # EXIF(위치 등)는 넣지 않는다
            return out.getvalue()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise PhotoError(messages.PHOTO_INVALID) from None


def parse_ids(value):
    """기록의 photo_ids 칸(JSON 목록 문자열) → 사진 ID 목록. 비었거나 깨졌으면 []."""
    if not value:
        return []
    try:
        ids = json.loads(value)
    except (TypeError, ValueError):
        return []
    return [str(i) for i in ids if isinstance(i, str) and i] if isinstance(ids, list) else []


def dump_ids(ids):
    return json.dumps(list(ids)) if ids else None
