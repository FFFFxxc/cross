import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from telethon.tl.types import MessageEntityBold, MessageEntityItalic

from tg_migrator.max_client import AmbiguousMaxSendError, MaxAttachment
from tg_migrator.publisher import PostPublisher, telegram_entities_to_max_html
from tg_migrator.state import MigrationState


class FakeTelegramClient:
    def __init__(self, messages):
        self.messages = messages
        self.forwarded = []
        self.edited = []
        self.downloaded = []

    async def get_messages(self, source, ids):
        return [self.messages[value] for value in ids]

    async def forward_messages(self, destination, ids, **kwargs):
        self.forwarded.append((destination, tuple(ids), kwargs))
        return [SimpleNamespace(id=500 + value) for value in ids]

    async def edit_message(self, destination, sent, **kwargs):
        self.edited.append((destination, sent.id, kwargs))

    async def download_media(self, message, file):
        path = Path(file)
        path.write_bytes(b"video-data")
        self.downloaded.append((message.id, path))
        return str(path)


class FakeMaxClient:
    def __init__(self, send_error=None):
        self.uploads = []
        self.sends = []
        self.send_error = send_error

    async def upload(self, path, media_type):
        self.uploads.append((Path(path), media_type))
        return MaxAttachment(media_type, {"token": f"token-{len(self.uploads)}"})

    async def send(self, text_html, attachments):
        self.sends.append((text_html, attachments))
        if self.send_error:
            raise self.send_error
        return "max-mid-7"


def video_message(message_id=1):
    text = "Жирный пост\nРеклама: https://bad.example"
    return SimpleNamespace(
        id=message_id,
        date=datetime(2026, 8, 13, 18, 0, tzinfo=timezone.utc),
        raw_text=text,
        message=text,
        entities=[MessageEntityBold(offset=0, length=6)],
        media=object(),
        video=object(),
        photo=None,
        document=SimpleNamespace(mime_type="video/mp4"),
        file=SimpleNamespace(ext=".mp4", size=25 * 1024 * 1024),
    )


class PublisherFormattingTests(unittest.TestCase):
    def test_converts_utf16_telegram_formatting_to_safe_max_html(self):
        text = "🙂 Жирный & курсив"
        bold = MessageEntityBold(offset=3, length=6)
        italic = MessageEntityItalic(offset=12, length=6)

        html = telegram_entities_to_max_html(text, [bold, italic])

        self.assertEqual(html, "🙂 <b>Жирный</b> &amp; <i>курсив</i>")


class PublisherTests(unittest.IsolatedAsyncioTestCase):
    async def test_publishes_clean_telegram_copy_then_large_video_to_max(self):
        with tempfile.TemporaryDirectory() as directory:
            state = MigrationState(Path(directory) / "state.sqlite3")
            item = state.enqueue(
                "animeworldmem",
                "message:1",
                (1,),
                "video",
                100,
                datetime.now(timezone.utc),
            )
            item = state.claim("video")
            telegram = FakeTelegramClient({1: video_message()})
            max_client = FakeMaxClient()
            publisher = PostPublisher(
                telegram,
                state,
                "webnmy",
                max_client,
                default_signature=("НАШ ТГК", "https://t.me/webm4ik"),
            )

            result = await publisher.publish(item)

            self.assertEqual(result.max_mid, "max-mid-7")
            self.assertEqual(telegram.forwarded[0][0], "webnmy")
            self.assertEqual(telegram.edited[0][2]["text"], "Жирный пост")
            self.assertEqual(len(telegram.edited[0][2]["formatting_entities"]), 1)
            self.assertEqual(telegram.downloaded[0][0], 1)
            self.assertEqual(max_client.uploads[0][1], "video")
            self.assertFalse(max_client.uploads[0][0].exists())
            self.assertEqual(
                max_client.sends[0][0],
                '<b>Жирный</b> пост\n\n<a href="https://t.me/webm4ik">НАШ ТГК</a>',
            )
            saved = state.queue_item(item.id)
            self.assertEqual(saved.status, "published")
            self.assertEqual(saved.telegram_message_ids, (501,))
            self.assertEqual(saved.max_mid, "max-mid-7")
            state.close()

    async def test_restart_skips_telegram_stage_when_delivery_was_saved(self):
        with tempfile.TemporaryDirectory() as directory:
            state = MigrationState(Path(directory) / "state.sqlite3")
            item = state.enqueue(
                "source", "message:1", (1,), "video", 1,
                datetime.now(timezone.utc),
            )
            state.claim("video")
            state.save_telegram_delivery(item.id, (777,))
            state.recover_interrupted()
            item = state.claim("video")
            telegram = FakeTelegramClient({1: video_message()})
            publisher = PostPublisher(
                telegram,
                state,
                "webnmy",
                FakeMaxClient(),
                default_signature=("НАШ ТГК", "https://t.me/webm4ik"),
            )

            await publisher.publish(item)

            self.assertEqual(telegram.forwarded, [])
            self.assertEqual(state.queue_item(item.id).status, "published")
            state.close()

    async def test_ambiguous_max_send_is_not_retried_automatically(self):
        with tempfile.TemporaryDirectory() as directory:
            state = MigrationState(Path(directory) / "state.sqlite3")
            item = state.enqueue(
                "source", "message:1", (1,), "video", 1,
                datetime.now(timezone.utc),
            )
            item = state.claim("video")
            publisher = PostPublisher(
                FakeTelegramClient({1: video_message()}),
                state,
                "webnmy",
                FakeMaxClient(AmbiguousMaxSendError("lost")),
                default_signature=("НАШ ТГК", "https://t.me/webm4ik"),
            )

            with self.assertRaises(AmbiguousMaxSendError):
                await publisher.publish(item)

            self.assertEqual(state.queue_item(item.id).status, "ambiguous")
            self.assertIsNone(state.claim("any"))
            state.close()


if __name__ == "__main__":
    unittest.main()
