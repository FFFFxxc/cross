import io
import unittest
from types import SimpleNamespace

from PIL import Image

from tg_migrator.previews import capture_preview


def png_bytes(size=(1800, 1200)) -> bytes:
    image = Image.effect_noise(size, 100).convert("RGB")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


class FakeClient:
    def __init__(self, data: bytes):
        self.data = data
        self.calls = []

    async def download_media(self, message, *, file, thumb=None):
        self.calls.append((message, file, thumb))
        return self.data


class PreviewTests(unittest.IsolatedAsyncioTestCase):
    async def test_photo_is_resized_and_encoded_below_database_limit(self):
        client = FakeClient(png_bytes())
        message = SimpleNamespace(photo=object(), video=None, document=None)

        preview = await capture_preview(client, (message,))

        self.assertEqual(preview.mime_type, "image/webp")
        self.assertLessEqual(len(preview.data), 131_072)
        with Image.open(io.BytesIO(preview.data)) as image:
            self.assertLessEqual(max(image.size), 720)

    async def test_video_uses_largest_telegram_thumbnail(self):
        client = FakeClient(png_bytes((640, 360)))
        message = SimpleNamespace(photo=None, video=object(), document=object())

        preview = await capture_preview(client, (message,))

        self.assertIsNotNone(preview)
        self.assertEqual(client.calls[0][2], -1)

    async def test_absent_invalid_or_failed_media_has_no_preview(self):
        no_media = SimpleNamespace(photo=None, video=None, document=None)
        self.assertIsNone(await capture_preview(FakeClient(b"ignored"), (no_media,)))

        invalid = SimpleNamespace(photo=object(), video=None, document=None)
        self.assertIsNone(await capture_preview(FakeClient(b"not an image"), (invalid,)))

        class BrokenClient(FakeClient):
            async def download_media(self, message, *, file, thumb=None):
                raise RuntimeError("Telegram unavailable")

        self.assertIsNone(await capture_preview(BrokenClient(b""), (invalid,)))


if __name__ == "__main__":
    unittest.main()
