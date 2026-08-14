import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from tg_migrator.automation import AutomationController, DEFAULT_SLOTS
from tg_migrator.config import AutomationConfig
from tg_migrator.state import MigrationState, Slot


def config(**overrides):
    values = {
        "enabled": True,
        "owner_ids": frozenset({8235497168}),
        "destination": "webnmy",
        "initial_source": "animeworldmem",
        "database_url": None,
        "max_token": "token",
        "max_channel": "channel_animenaruto",
        "max_api_base": "https://platform-api2.max.ru",
        "signature_text": "НАШ ТГК",
        "signature_url": "https://t.me/webm4ik",
        "queue_minimum": 2,
        "refill_interval": 900,
        "scan_limit": 10,
        "fresh_days": 30,
        "target_scan_limit": 1000,
    }
    values.update(overrides)
    return AutomationConfig(**values)


def message(message_id, *, chat_id=-100, video=True, views=0):
    return SimpleNamespace(
        id=message_id,
        chat_id=chat_id,
        date=datetime(2026, 8, 13, 12 + message_id % 10, tzinfo=timezone.utc),
        raw_text=f"post {message_id}",
        message=f"post {message_id}",
        entities=[],
        media=object() if video else None,
        video=object() if video else None,
        photo=None,
        document=(
            SimpleNamespace(mime_type="video/mp4", id=message_id)
            if video
            else None
        ),
        grouped_id=None,
        action=None,
        views=views,
        forwards=0,
        reactions=None,
    )


class Reply:
    def __init__(self, text):
        self.text = text

    async def edit(self, text):
        self.text = text


class Event:
    def __init__(
        self,
        text="",
        *,
        outgoing=False,
        chat_id=8235497168,
        sender_id=8235497168,
    ):
        self.raw_text = text
        self.outgoing = outgoing
        self.is_private = True
        self.chat_id = chat_id
        self.sender_id = sender_id
        self.responses = []

    async def respond(self, text):
        self.responses.append(text)
        return Reply(text)


class FakeClient:
    def __init__(self, posts=None):
        self.posts = posts or {}
        self.joined = []
        self.sent = []

    async def get_me(self):
        return SimpleNamespace(id=8528395173)

    async def __call__(self, request):
        self.joined.append(request)
        return SimpleNamespace(chats=[])

    async def get_entity(self, peer):
        name = str(peer).replace("@", "")
        return SimpleNamespace(id=-100 if name == "animeworldmem" else -200, username=name, title=name)

    async def get_dialogs(self):
        return []

    def iter_messages(self, source, limit=None):
        values = list(self.posts.get(str(source), ()))[:limit]

        async def iterator():
            for value in values:
                yield value

        return iterator()

    async def send_message(self, peer, text):
        self.sent.append((peer, text))


class FakePublisher:
    def __init__(self, state):
        self.state = state
        self.calls = []
        self.max_client = SimpleNamespace()

    async def publish(self, item):
        self.calls.append(item)
        self.state.complete(item.id, f"mid-{len(self.calls)}")
        return SimpleNamespace(max_mid=f"mid-{len(self.calls)}")


class AutomationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.state = MigrationState(Path(self.directory.name) / "state.sqlite3")

    async def asyncTearDown(self):
        self.state.close()
        self.directory.cleanup()

    async def controller(self, client=None, **overrides):
        publisher = FakePublisher(self.state)
        controller = AutomationController(
            client or FakeClient(),
            self.state,
            publisher,
            config(**overrides),
        )
        await controller.initialize()
        return controller, publisher

    async def test_initializes_default_source_slots_and_two_authorized_chats(self):
        controller, _ = await self.controller()

        self.assertEqual([source.peer for source in self.state.sources()], ["animeworldmem"])
        self.assertEqual(self.state.slots(), list(DEFAULT_SLOTS))
        self.assertTrue(
            controller.is_authorized(Event(outgoing=True, chat_id=8528395173))
        )
        self.assertTrue(controller.is_authorized(Event(sender_id=8235497168)))
        self.assertFalse(controller.is_authorized(Event(sender_id=999)))

    async def test_saved_messages_uses_real_telethon_out_flag(self):
        controller, _ = await self.controller()
        event = SimpleNamespace(
            is_private=True,
            out=True,
            chat_id=8528395173,
            sender_id=8528395173,
        )

        self.assertTrue(controller.is_authorized(event))

    async def test_bare_telegram_link_adds_source_once(self):
        controller, _ = await self.controller()
        event = Event("https://t.me/new_source")

        self.assertTrue(await controller.handle_command(event, event.raw_text))
        self.assertTrue(await controller.handle_command(event, event.raw_text))

        self.assertEqual(
            [source.peer for source in self.state.sources()],
            ["animeworldmem", "new_source"],
        )
        self.assertIn("уже", event.responses[-1].lower())

    async def test_private_source_is_restored_from_dialogs_after_restart(self):
        class PrivateClient(FakeClient):
            async def get_entity(self, peer):
                if str(peer) == "-777":
                    raise ValueError("entity cache is empty")
                return await super().get_entity(peer)

            async def get_dialogs(self):
                entity = SimpleNamespace(id=-777, username=None, title="private")
                return [SimpleNamespace(entity=entity)]

        self.state.add_source("-777", "private")
        controller, _ = await self.controller(PrivateClient())

        self.assertTrue(
            await controller.handle_new_post([message(7, chat_id=-777)], chat_id=-777)
        )
        self.assertEqual(self.state.pending_count(), 1)

    async def test_parse_fills_queue_without_duplicates(self):
        client = FakeClient({"animeworldmem": [message(3), message(2), message(1)]})
        controller, _ = await self.controller(client)
        event = Event("/parse 2")

        await controller.handle_command(event, event.raw_text)
        await controller.handle_command(event, event.raw_text)

        self.assertEqual(self.state.queue_counts(), {"pending": 2})
        self.assertIn("Добавлено: 0", event.responses[-1])

    async def test_commands_change_typed_slot_and_signature(self):
        controller, _ = await self.controller()
        await controller.handle_command(Event(), "/slot 14:00 video animeworldmem")
        await controller.handle_command(
            Event(),
            "/signature МОЙ КАНАЛ | https://t.me/custom",
        )

        self.assertEqual(
            next(slot for slot in self.state.slots() if slot.time == "14:00"),
            Slot("14:00", "video", "animeworldmem"),
        )
        self.assertEqual(self.state.get_setting("signature_text"), "МОЙ КАНАЛ")
        self.assertEqual(self.state.get_setting("signature_url"), "https://t.me/custom")

    async def test_max_status_reports_official_channel_id(self):
        controller, publisher = await self.controller()

        async def discover_channels():
            return [
                {
                    "chat_id": -77809668353385,
                    "title": "Аниме / 2D WEBM",
                    "link": "https://max.ru/channel_animenaruto",
                    "is_admin": True,
                    "can_write": True,
                    "permissions": ["write"],
                    "membership_error": "",
                }
            ]

        async def bot_info():
            return {
                "user_id": 12345,
                "name": "Crossposter",
                "username": "crossposter_bot",
            }

        publisher.max_client.discover_channels = discover_channels
        publisher.max_client.bot_info = bot_info
        event = Event("/max_status", outgoing=True, chat_id=8528395173)

        self.assertTrue(await controller.handle_command(event, event.raw_text))
        self.assertIn("-77809668353385", event.responses[-1])
        self.assertIn("Аниме / 2D WEBM", event.responses[-1])
        self.assertIn("Crossposter (@crossposter_bot, ID 12345)", event.responses[-1])
        self.assertIn("админ: да", event.responses[-1])
        self.assertIn("публикация: да", event.responses[-1])

    async def test_video_slot_claims_video_and_runs_only_once(self):
        controller, publisher = await self.controller()
        image = self.state.enqueue(
            "animeworldmem", "message:1", (1,), "image", 100,
            datetime.now(timezone.utc),
        )
        video = self.state.enqueue(
            "animeworldmem", "message:2", (2,), "video", 1,
            datetime.now(timezone.utc),
        )

        now = datetime(2026, 8, 14, 14, 5, tzinfo=controller.timezone)
        await controller.run_due(now)
        await controller.run_due(now)

        self.assertEqual([item.id for item in publisher.calls], [video.id])
        self.assertEqual(self.state.queue_item(image.id).status, "pending")

    async def test_stale_slot_is_not_caught_up_after_late_restart(self):
        controller, publisher = await self.controller()
        item = self.state.enqueue(
            "animeworldmem", "message:18", (18,), "image", 1,
            datetime.now(timezone.utc),
        )

        published = await controller.run_due(
            datetime(2026, 8, 14, 18, 10, tzinfo=controller.timezone)
        )

        self.assertFalse(published)
        self.assertEqual(publisher.calls, [])
        self.assertEqual(self.state.queue_item(item.id).status, "pending")

    async def test_refill_stops_at_queue_minimum(self):
        client = FakeClient(
            {"animeworldmem": [message(5), message(4), message(3), message(2), message(1)]}
        )
        controller, _ = await self.controller(client, queue_minimum=2)

        added = await controller.refill()

        self.assertEqual(added, 2)
        self.assertEqual(self.state.pending_count(), 2)

    async def test_refill_scans_past_already_published_latest_posts(self):
        client = FakeClient(
            {"animeworldmem": [message(5), message(4), message(3), message(2), message(1)]}
        )
        controller, _ = await self.controller(client, queue_minimum=2, scan_limit=5)
        await controller.parse_latest(2)
        for _ in range(2):
            item = self.state.claim("any")
            self.state.complete(item.id, f"old-{item.id}")

        added = await controller.refill()

        self.assertEqual(added, 2)
        self.assertEqual(self.state.pending_count(), 2)

    async def test_empty_slot_is_recorded_once_instead_of_spamming(self):
        client = FakeClient()
        controller, _ = await self.controller(client)
        now = datetime(2026, 8, 14, 14, 0, tzinfo=controller.timezone)

        await controller.run_due(now)
        await controller.run_due(now)

        self.assertEqual(len(client.sent), 2)

    async def test_new_source_post_is_enqueued_once(self):
        controller, _ = await self.controller()
        post = message(1, chat_id=-100)

        self.assertTrue(await controller.handle_new_post([post], chat_id=-100))
        self.assertFalse(await controller.handle_new_post([post], chat_id=-100))
        self.assertEqual(self.state.pending_count(), 1)

    async def test_target_history_prevents_first_neon_queue_duplicates(self):
        already_published = message(90)
        already_published.document.id = 777
        source_copy = message(1)
        source_copy.document.id = 777
        client = FakeClient(
            {
                "webnmy": [already_published],
                "animeworldmem": [source_copy],
            }
        )
        controller, _ = await self.controller(client)

        added = await controller.parse_latest(1)

        self.assertEqual(added, 0)
        self.assertEqual(self.state.pending_count(), 0)

    async def test_now_publishes_without_consuming_schedule_slot(self):
        controller, publisher = await self.controller()
        self.state.enqueue(
            "animeworldmem", "message:1", (1,), "video", 1,
            datetime.now(timezone.utc),
        )

        await controller.handle_command(Event(), "/now video")

        self.assertEqual(len(publisher.calls), 1)
        self.assertTrue(self.state.claim_slot(datetime(2026, 8, 14).date(), "14:00"))


if __name__ == "__main__":
    unittest.main()
