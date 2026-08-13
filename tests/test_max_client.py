import tempfile
import unittest
from pathlib import Path

import httpx

from tg_migrator.max_client import (
    AmbiguousMaxSendError,
    MaxAttachment,
    MaxClient,
    MaxConfig,
)


class MaxClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolves_public_channel_link_to_chat_id(self):
        async def handler(request):
            self.assertEqual(request.method, "GET")
            self.assertEqual(request.url.path, "/chats/channel_animenaruto")
            self.assertEqual(request.headers["authorization"], "token")
            return httpx.Response(200, json={"chat_id": -7123, "type": "channel"})

        client = MaxClient(
            MaxConfig("token", "channel_animenaruto"),
            transport=httpx.MockTransport(handler),
        )
        try:
            self.assertEqual(await client.resolve_channel(), -7123)
        finally:
            await client.aclose()

    async def test_uploads_video_from_file_without_caller_reading_it(self):
        requests = []

        async def handler(request):
            requests.append(request)
            if request.url.path == "/uploads":
                self.assertEqual(request.url.params["type"], "video")
                return httpx.Response(
                    200,
                    json={"url": "https://upload.test/video", "token": "video-token"},
                )
            self.assertEqual(str(request.url), "https://upload.test/video")
            body = await request.aread()
            self.assertIn(b"large-video-content", body)
            self.assertIn("multipart/form-data", request.headers["content-type"])
            return httpx.Response(200, json={"retval": {"ok": True}})

        client = MaxClient(
            MaxConfig("token", "channel_animenaruto"),
            transport=httpx.MockTransport(handler),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "edit.mp4"
            path.write_bytes(b"large-video-content")
            try:
                attachment = await client.upload(path, "video")
            finally:
                await client.aclose()

        self.assertEqual(
            attachment,
            MaxAttachment("video", {"token": "video-token"}),
        )
        self.assertEqual(len(requests), 2)

    async def test_retries_attachment_processing_and_reads_body_mid(self):
        message_calls = 0
        waits = []

        async def handler(request):
            nonlocal message_calls
            message_calls += 1
            payload = __import__("json").loads((await request.aread()).decode())
            self.assertEqual(payload["text"], "<b>Пост</b>")
            self.assertEqual(payload["attachments"][0]["type"], "video")
            if message_calls == 1:
                return httpx.Response(
                    400,
                    json={
                        "code": "attachment.not.ready",
                        "message": "not processed",
                    },
                )
            return httpx.Response(
                200,
                json={"message": {"body": {"mid": "max-mid-42"}}},
            )

        async def no_wait(seconds):
            waits.append(seconds)

        client = MaxClient(
            MaxConfig("token", "-500"),
            transport=httpx.MockTransport(handler),
            sleep=no_wait,
        )
        try:
            mid = await client.send(
                "<b>Пост</b>",
                [MaxAttachment("video", {"token": "ready-later"})],
            )
        finally:
            await client.aclose()

        self.assertEqual(mid, "max-mid-42")
        self.assertEqual(message_calls, 2)
        self.assertEqual(waits, [1])

    async def test_transport_error_during_message_send_is_ambiguous(self):
        async def handler(request):
            raise httpx.ReadTimeout("connection lost", request=request)

        client = MaxClient(
            MaxConfig("token", "-500"),
            transport=httpx.MockTransport(handler),
        )
        try:
            with self.assertRaises(AmbiguousMaxSendError):
                await client.send("Пост", [])
        finally:
            await client.aclose()


if __name__ == "__main__":
    unittest.main()
