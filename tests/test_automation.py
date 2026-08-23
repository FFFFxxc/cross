import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import random
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


def message(
    message_id,
    *,
    chat_id=-100,
    video=True,
    views=0,
    forwards=0,
    reactions=0,
    published_at=None,
):
    reaction_results = (
        [SimpleNamespace(count=reactions)] if reactions else []
    )
    return SimpleNamespace(
        id=message_id,
        chat_id=chat_id,
        date=published_at or datetime(
            2026, 8, 13, 12 + message_id % 10, tzinfo=timezone.utc
        ),
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
        forwards=forwards,
        reactions=SimpleNamespace(results=reaction_results),
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

    async def get_messages(self, source, ids):
        by_id = {
            value.id: value
            for value in self.posts.get(str(source), ())
        }
        return [by_id.get(int(message_id)) for message_id in ids]

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

    async def test_parse_prefers_high_engagement_over_empty_reach(self):
        now = datetime.now(timezone.utc)
        high_reach = message(
            1,
            views=10_000,
            reactions=0,
            published_at=now,
        )
        high_engagement = message(
            2,
            views=1_000,
            reactions=200,
            published_at=now,
        )
        client = FakeClient({"animeworldmem": [high_engagement, high_reach]})
        controller, _ = await self.controller(client)

        await controller.parse_latest(1, scan_count=2)

        claimed = self.state.claim()
        self.assertEqual(claimed.message_ids, (2,))

    async def test_parse_ignores_posts_older_than_fresh_window(self):
        now = datetime.now(timezone.utc)
        client = FakeClient(
            {
                "animeworldmem": [
                    message(2, published_at=now - timedelta(days=1)),
                    message(1, published_at=now - timedelta(days=8)),
                ]
            }
        )
        controller, _ = await self.controller(client, fresh_days=7)

        added = await controller.parse_latest(2, scan_count=2)

        self.assertEqual(added, 1)
        self.assertEqual(self.state.claim().message_ids, (2,))

    async def test_publish_skips_stale_items_already_in_queue(self):
        now = datetime.now(timezone.utc)
        stale = self.state.enqueue(
            "animeworldmem",
            "message:1",
            (1,),
            "video",
            100_000,
            now - timedelta(days=8),
        )
        fresh = self.state.enqueue(
            "animeworldmem",
            "message:2",
            (2,),
            "video",
            1,
            now - timedelta(days=1),
        )
        controller, publisher = await self.controller(fresh_days=7)

        published = await controller.publish_next(refill=False)

        self.assertEqual(published.id, fresh.id)
        self.assertEqual(self.state.queue_item(stale.id).status, "expired")
        self.assertEqual([item.id for item in publisher.calls], [fresh.id])

    async def test_publish_refreshes_activity_before_choosing(self):
        now = datetime.now(timezone.utc)
        stale_score = self.state.enqueue(
            "animeworldmem", "message:1", (1,), "video", 100_000, now
        )
        newly_popular = self.state.enqueue(
            "animeworldmem", "message:2", (2,), "video", 1, now
        )
        client = FakeClient(
            {
                "animeworldmem": [
                    message(1, views=10_000, published_at=now),
                    message(2, views=1_000, reactions=200, published_at=now),
                ]
            }
        )
        controller, publisher = await self.controller(client)
        controller._rng = random.Random(1)

        published = await controller.publish_next(refill=False)

        self.assertEqual(published.id, newly_popular.id)
        self.assertGreater(
            self.state.queue_item(newly_popular.id).score,
            self.state.queue_item(stale_score.id).score,
        )
        self.assertEqual([item.id for item in publisher.calls], [newly_popular.id])

    async def test_publish_uses_weighted_choice_inside_top_five(self):
        now = datetime.now(timezone.utc)
        items = [
            self.state.enqueue(
                "animeworldmem",
                f"message:{index}",
                (index,),
                "video",
                score,
                now,
            )
            for index, score in enumerate((500, 400, 300, 200, 100, 1), start=1)
        ]
        controller, publisher = await self.controller()
        controller._rng = random.Random(0)

        published = await controller.publish_next(refill=False)

        self.assertEqual(published.id, items[2].id)
        self.assertEqual([item.id for item in publisher.calls], [items[2].id])
        self.assertEqual(self.state.queue_item(items[5].id).status, "pending")

    async def test_publish_rotates_away_from_previous_source(self):
        now = datetime.now(timezone.utc)
        previous_source_items = [
            self.state.enqueue(
                "source-a",
                f"message:{index}",
                (index,),
                "video",
                10_000 - index,
                now,
            )
            for index in range(1, 6)
        ]
        other_source = self.state.enqueue(
            "source-b", "message:20", (20,), "video", 1, now
        )
        self.state.set_setting("last_published_source", "source-a")
        controller, publisher = await self.controller(scan_limit=5)
        controller._rng = random.Random(1)

        published = await controller.publish_next(refill=False)

        self.assertEqual(published.id, other_source.id)
        self.assertTrue(
            all(
                self.state.queue_item(item.id).status == "pending"
                for item in previous_source_items
            )
        )
        self.assertEqual(
            self.state.get_setting("last_published_source"),
            "source-b",
        )
        self.assertEqual([item.id for item in publisher.calls], [other_source.id])

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

    async def test_fresh_days_command_changes_smart_window(self):
        controller, _ = await self.controller()
        update = Event("/fresh_days 7")
        show = Event("/fresh_days")

        self.assertTrue(await controller.handle_command(update, update.raw_text))
        self.assertTrue(await controller.handle_command(show, show.raw_text))

        self.assertEqual(self.state.get_setting("fresh_days"), "7")
        self.assertIn("7", show.responses[-1])

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

    async def test_max_status_reports_bot_lookup_error_without_crashing(self):
        controller, publisher = await self.controller()

        async def discover_channels():
            return [
                {
                    "chat_id": -77809668353385,
                    "title": "настроенный канал",
                    "link": "",
                    "is_admin": False,
                    "can_write": False,
                    "permissions": [],
                    "membership_error": "Chat not found",
                }
            ]

        async def bot_info():
            raise RuntimeError("Bot lookup failed")

        publisher.max_client.discover_channels = discover_channels
        publisher.max_client.bot_info = bot_info
        event = Event("/max_status", outgoing=True, chat_id=8528395173)

        self.assertTrue(await controller.handle_command(event, event.raw_text))
        self.assertIn("MAX-бот Render: не определён", event.responses[-1])
        self.assertIn("Bot lookup failed", event.responses[-1])
        self.assertIn("-77809668353385", event.responses[-1])

    async def test_max_probe_sends_directly_to_max_without_touching_queue(self):
        controller, publisher = await self.controller()
        item = self.state.enqueue(
            "animeworldmem", "message:90", (90,), "video", 1,
            datetime.now(timezone.utc),
        )
        calls = []

        async def send(text_html, attachments):
            calls.append((text_html, attachments))
            return "max-probe-mid"

        publisher.max_client.send = send
        event = Event("/max_probe", outgoing=True, chat_id=8528395173)

        self.assertTrue(await controller.handle_command(event, event.raw_text))
        self.assertEqual(calls, [("Проверка связи Desiree", [])])
        self.assertEqual(self.state.queue_item(item.id).status, "pending")
        self.assertIn("MAX отвечает", event.responses[-1])
        self.assertIn("max-probe-mid", event.responses[-1])

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
