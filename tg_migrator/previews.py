from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any, Iterable

from PIL import Image, ImageOps, UnidentifiedImageError


@dataclass(frozen=True)
class Preview:
    mime_type: str
    data: bytes


def _bounded_webp(raw: bytes, max_bytes: int) -> bytes | None:
    try:
        with Image.open(io.BytesIO(raw)) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
    except (OSError, ValueError, UnidentifiedImageError):
        return None

    image.thumbnail((720, 720), Image.Resampling.LANCZOS)
    while image.width > 0 and image.height > 0:
        for quality in (76, 68, 60, 52, 48):
            output = io.BytesIO()
            image.save(output, format="WEBP", quality=quality, method=4)
            data = output.getvalue()
            if len(data) <= max_bytes:
                return data
        next_size = (
            max(1, int(image.width * 0.85)),
            max(1, int(image.height * 0.85)),
        )
        if next_size == image.size:
            return None
        image = image.resize(next_size, Image.Resampling.LANCZOS)
    return None


async def capture_preview(
    client: Any,
    messages: Iterable[Any],
    max_bytes: int = 131_072,
) -> Preview | None:
    if max_bytes <= 0:
        return None
    candidate = next(
        (
            message
            for message in messages
            if getattr(message, "photo", None) is not None
            or getattr(message, "video", None) is not None
            or getattr(message, "document", None) is not None
        ),
        None,
    )
    if candidate is None:
        return None
    try:
        raw = await client.download_media(candidate, file=bytes, thumb=-1)
    except Exception:
        return None
    if not isinstance(raw, (bytes, bytearray)):
        return None
    encoded = _bounded_webp(bytes(raw), max_bytes)
    if encoded is None:
        return None
    return Preview("image/webp", encoded)
