import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from tg_migrator.automation import AutomationController, DEFAULT_SLOTS
from tg_migrator.config import AutomationConfig
from tg_migrator.previews import Preview
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
        self.assertEqual(self.state.pending_count(), 0)
        self.assertEqual(len(self.state.pool_items()), 1)

    async def test_parse_fills_queue_without_duplicates(self):
        client = FakeClient({"animeworldmem": [message(3), message(2), message(1)]})
        controller, _ = await self.controller(client)
        event = Event("/parse 2")

        await controller.handle_command(event, event.raw_text)
        await controller.handle_command(event, event.raw_text)

        self.assertEqual(self.state.pending_count(), 2)
        self.assertEqual(len(self.state.pool_items()), 3)

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

    async def test_parse_and_refresh_persist_live_engagement_metadata(self):
        now = datetime.now(timezone.utc)
        original = message(
            1,
            views=1_000,
            forwards=4,
            reactions=20,
            published_at=now,
        )
        client = FakeClient({"animeworldmem": [original]})
        controller, _ = await self.controller(client)

        await controller.parse_latest(1)
        item = self.state.pending_items()[0]
        self.assertEqual(item.caption_excerpt, "post 1")
        self.assertEqual(item.views_count, 1_000)
        self.assertEqual(item.reactions_count, 20)
        self.assertEqual(item.forwards_count, 4)

        original.views = 7_500
        original.forwards = 10
        original.reactions.results[0].count = 140
        await controller._refresh_pending_scores()
        refreshed = self.state.queue_item(item.id)
        self.assertEqual(refreshed.views_count, 7_500)
        self.assertEqual(refreshed.reactions_count, 140)
        self.assertEqual(refreshed.forwards_count, 10)

    async def test_preview_is_captured_only_for_new_queue_item(self):
        now = datetime.now(timezone.utc)
        client = FakeClient(
            {"animeworldmem": [message(1, views=10, published_at=now)]}
        )
        controller, _ = await self.controller(client)
        preview = Preview("image/webp", b"small-preview")

        with patch(
            "tg_migrator.automation.capture_preview",
            new=AsyncMock(return_value=preview),
        ) as capture:
            self.assertEqual(await controller.parse_latest(1), 1)
            self.assertEqual(await controller.parse_latest(1), 0)

        self.assertEqual(capture.await_count, 1)
        saved = self.state.pending_items()[0]
        self.assertEqual(saved.preview_mime, "image/webp")
        self.assertEqual(saved.preview_data, b"small-preview")

    async def test_score_refresh_backfills_a_missing_preview_only_once(self):
        now = datetime.now(timezone.utc)
        original = message(1, views=10, published_at=now)
        client = FakeClient({"animeworldmem": [original]})
        controller, _ = await self.controller(client)
        item = self.state.enqueue(
            "animeworldmem",
            "message:1",
            (1,),
            "video",
            10,
            now,
        )
        preview = Preview("image/webp", b"backfilled-preview")

        with patch(
            "tg_migrator.automation.capture_preview",
            new=AsyncMock(return_value=preview),
        ) as capture:
            await controller._refresh_pending_scores()
            await controller._refresh_pending_scores()

        saved = self.state.queue_item(item.id)
        self.assertEqual(saved.preview_mime, "image/webp")
        self.assertEqual(saved.preview_data, b"backfilled-preview")
        self.assertEqual(capture.await_count, 1)

    async def test_score_refresh_backfills_previews_beyond_the_scan_limit(self):
        now = datetime.now(timezone.utc)
        posts = [
            message(1, views=20, published_at=now),
            message(2, views=10, published_at=now),
        ]
        client = FakeClient({"animeworldmem": posts})
        controller, _ = await self.controller(client, scan_limit=1)
        items = [
            self.state.enqueue(
                "animeworldmem",
                f"message:{post.id}",
                (post.id,),
                "video",
                post.views,
                now,
                status="candidate",
            )
            for post in posts
        ]

        with patch(
            "tg_migrator.automation.capture_preview",
            new=AsyncMock(return_value=Preview("image/webp", b"preview")),
        ):
            await controller._refresh_pending_scores()

        self.assertTrue(all(self.state.queue_item(item.id).preview_data for item in items))

    async def test_preview_backfill_does_not_unbound_score_refresh(self):
        class TrackingClient(FakeClient):
            def __init__(self, posts):
                super().__init__(posts)
                self.requested_ids = []

            async def get_messages(self, source, ids):
                self.requested_ids.append(tuple(ids))
                return await super().get_messages(source, ids)

        now = datetime.now(timezone.utc)
        posts = [
            message(index, views=index, published_at=now)
            for index in range(1, 21)
        ]
        client = TrackingClient({"animeworldmem": posts})
        controller, _ = await self.controller(
            client,
            scan_limit=1,
            queue_minimum=2,
        )
        for post in posts:
            item = self.state.enqueue(
                "animeworldmem",
                f"message:{post.id}",
                (post.id,),
                "video",
                post.views,
                now,
                status="candidate",
            )
            if post.id != 1:
                self.state.update_post_metadata(
                    item.id,
                    preview_mime="image/webp",
                    preview_data=b"existing",
                )

        with patch(
            "tg_migrator.automation.capture_preview",
            new=AsyncMock(return_value=Preview("image/webp", b"backfilled")),
        ):
            await controller._refresh_pending_scores()

        self.assertEqual(set(client.requested_ids[0]), {1, 20})

    async def test_failed_preview_attempts_do_not_starve_lower_posts(self):
        now = datetime.now(timezone.utc)
        posts = [
            message(index, views=index, published_at=now)
            for index in range(1, 4)
        ]
        client = FakeClient({"animeworldmem": posts})
        controller, _ = await self.controller(
            client,
            scan_limit=1,
            queue_minimum=2,
        )
        items = {}
        for post in posts:
            items[post.id] = self.state.enqueue(
                "animeworldmem",
                f"message:{post.id}",
                (post.id,),
                "video",
                post.views,
                now,
                status="candidate",
            )

        async def preview_for_lowest(_client, messages):
            if messages[0].id == 1:
                return Preview("image/webp", b"lowest-preview")
            return None

        with patch(
            "tg_migrator.automation.capture_preview",
            new=AsyncMock(side_effect=preview_for_lowest),
        ):
            await controller._refresh_pending_scores()
            await controller._refresh_pending_scores()

        self.assertEqual(
            self.state.queue_item(items[1].id).preview_data,
            b"lowest-preview",
        )

    async def test_deleted_messages_do_not_starve_preview_backfill(self):
        now = datetime.now(timezone.utc)
        available = message(1, views=1, published_at=now)
        client = FakeClient({"animeworldmem": [available]})
        controller, _ = await self.controller(
            client,
            scan_limit=1,
            queue_minimum=2,
        )
        items = {}
        for message_id in (1, 2, 3):
            items[message_id] = self.state.enqueue(
                "animeworldmem",
                f"message:{message_id}",
                (message_id,),
                "video",
                message_id,
                now,
                status="candidate",
            )

        with patch(
            "tg_migrator.automation.capture_preview",
            new=AsyncMock(return_value=Preview("image/webp", b"available")),
        ):
            await controller._refresh_pending_scores()
            await controller._refresh_pending_scores()

        self.assertEqual(
            self.state.queue_item(items[1].id).preview_data,
            b"available",
        )

    async def test_concurrent_refreshes_capture_a_preview_once(self):
        now = datetime.now(timezone.utc)
        original = message(1, views=1, published_at=now)
        client = FakeClient({"animeworldmem": [original]})
        controller, _ = await self.controller(client)
        self.state.enqueue(
            "animeworldmem",
            "message:1",
            (1,),
            "video",
            1,
            now,
            status="candidate",
        )

        async def delayed_preview(_client, _messages):
            await asyncio.sleep(0)
            return Preview("image/webp", b"single-preview")

        with patch(
            "tg_migrator.automation.capture_preview",
            new=AsyncMock(side_effect=delayed_preview),
        ) as capture:
            await asyncio.gather(
                controller._refresh_pending_scores(),
                controller._refresh_pending_scores(),
            )

        self.assertEqual(capture.await_count, 1)

    async def test_automatic_thresholds_filter_but_manual_claim_bypasses_them(self):
        now = datetime.now(timezone.utc)
        below_reactions = self.state.enqueue(
            "animeworldmem", "message:1", (1,), "video", 300, now
        )
        below_views = self.state.enqueue(
            "animeworldmem", "message:2", (2,), "video", 200, now
        )
        eligible = self.state.enqueue(
            "animeworldmem", "message:3", (3,), "video", 100, now
        )
        self.state.update_post_metadata(
            below_reactions.id, views_count=8_000, reactions_count=99
        )
        self.state.update_post_metadata(
            below_views.id, views_count=4_999, reactions_count=200
        )
        self.state.update_post_metadata(
            eligible.id, views_count=5_000, reactions_count=100
        )
        self.state.set_setting("min_reactions", "100")
        self.state.set_setting("min_views", "5000")
        controller, _ = await self.controller()

        self.assertEqual(controller._claim_smart().id, eligible.id)
        self.assertIsNone(controller._claim_smart())
        self.assertEqual(self.state.claim_item(below_reactions.id).id, below_reactions.id)

        self.state.set_setting("min_reactions", "0")
        self.state.set_setting("min_views", "0")
        self.assertEqual(controller._claim_smart().id, below_views.id)

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

    async def test_news_parse_uses_only_news_sources_and_two_day_window(self):
        now = datetime.now(timezone.utc)
        self.state.add_source("anime-news", "Anime News", "news")
        client = FakeClient(
            {
                "animeworldmem": [message(1, views=99_000, published_at=now)],
                "anime-news": [
                    message(3, published_at=now - timedelta(hours=2)),
                    message(2, views=50_000, published_at=now - timedelta(hours=49)),
                ],
            }
        )
        controller, _ = await self.controller(client)

        added = await controller.parse_latest(5, required_kind="news")

        self.assertEqual(added, 1)
        news = self.state.pool_items(content_category="news")
        self.assertEqual([(item.source, item.message_ids) for item in news], [
            ("anime-news", (3,)),
        ])
        self.assertEqual(self.state.pool_items(content_category="content"), [])

    async def test_parse_rejects_advertising_marker_before_queue(self):
        now = datetime.now(timezone.utc)
        client = FakeClient(
            {
                "animeworldmem": [
                    message(2, published_at=now),
                    message(1, published_at=now),
                ]
            }
        )
        client.posts["animeworldmem"][0].raw_text = "Реклама. ООО Партнёр"
        client.posts["animeworldmem"][0].message = "Реклама. ООО Партнёр"
        client.posts["animeworldmem"][1].raw_text = "Рекламная иллюстрация аниме"
        client.posts["animeworldmem"][1].message = "Рекламная иллюстрация аниме"
        controller, _ = await self.controller(client)

        added = await controller.parse_latest(10)

        self.assertEqual(added, 1)
        self.assertEqual(self.state.pool_items()[0].message_ids, (1,))

    async def test_initialize_skips_existing_advertising_candidates(self):
        item = self.state.enqueue(
            "animeworldmem",
            "message:9",
            (9,),
            "image",
            10,
            datetime.now(timezone.utc),
            status="candidate",
        )
        self.state.update_post_metadata(
            item.id,
            caption_excerpt="Полезный сервис. #реклама",
        )

        controller, _ = await self.controller()

        self.assertEqual(controller._news_fresh_days(), 2)
        self.assertEqual(self.state.queue_item(item.id).status, "skipped")

    async def test_news_publish_prefers_newest_and_ignores_thresholds(self):
        now = datetime.now(timezone.utc)
        older = self.state.enqueue(
            "anime-news", "message:1", (1,), "image", 999_999,
            now - timedelta(days=1), content_category="news",
        )
        newest = self.state.enqueue(
            "anime-news", "message:2", (2,), "video", 1,
            now - timedelta(minutes=5), content_category="news",
        )
        self.state.set_setting("min_reactions", "100000")
        self.state.set_setting("min_views", "100000")
        controller, publisher = await self.controller()

        published = await controller.publish_next("news", refill=False)

        self.assertEqual(published.id, newest.id)
        self.assertEqual([item.id for item in publisher.calls], [newest.id])
        self.assertIn(
            self.state.queue_item(older.id).status,
            {"pending", "candidate"},
        )

    async def test_news_publish_expires_only_stale_news(self):
        now = datetime.now(timezone.utc)
        stale_news = self.state.enqueue(
            "anime-news", "message:1", (1,), "image", 100,
            now - timedelta(days=4), content_category="news",
        )
        fresh_content = self.state.enqueue(
            "animeworldmem", "message:2", (2,), "image", 1,
            now - timedelta(days=4), content_category="content",
        )
        controller, _ = await self.controller(fresh_days=30)

        self.assertIsNone(await controller.publish_next("news", refill=False))

        self.assertEqual(self.state.queue_item(stale_news.id).status, "expired")
        self.assertIn(
            self.state.queue_item(fresh_content.id).status,
            {"pending", "candidate"},
        )

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

    async def test_publish_item_claims_exact_manual_choice(self):
        now = datetime.now(timezone.utc)
        first = self.state.enqueue(
            "animeworldmem", "message:1", (1,), "video", 1000, now
        )
        chosen = self.state.enqueue(
            "animeworldmem", "message:2", (2,), "video", 1, now,
            status="candidate",
        )
        controller, publisher = await self.controller()

        published = await controller.publish_item(chosen.id)

        self.assertEqual(published.id, chosen.id)
        self.assertEqual([item.id for item in publisher.calls], [chosen.id])
        self.assertEqual(self.state.queue_item(first.id).status, "pending")
        with self.assertRaisesRegex(ValueError, "обработан|недоступен"):
            await controller.publish_item(chosen.id)

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

        published = await controller.publish_next(refill=False)

        self.assertEqual(published.id, newly_popular.id)
        self.assertGreater(
            self.state.queue_item(newly_popular.id).score,
            self.state.queue_item(stale_score.id).score,
        )
        self.assertEqual([item.id for item in publisher.calls], [newly_popular.id])

    async def test_publish_uses_highest_ranked_item(self):
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

        published = await controller.publish_next(refill=False)

        self.assertEqual(published.id, items[0].id)
        self.assertEqual([item.id for item in publisher.calls], [items[0].id])
        self.assertEqual(self.state.queue_item(items[5].id).status, "candidate")

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

        published = await controller.publish_next(refill=False)

        self.assertEqual(published.id, other_source.id)
        self.assertTrue(all(
            self.state.queue_item(item.id).status in {"pending", "candidate"}
            for item in previous_source_items
        ))
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

    async def test_news_commands_add_categorize_and_schedule_source(self):
        controller, _ = await self.controller()

        await controller.handle_command(
            Event(),
            "/add_source https://t.me/anime_news news",
        )
        await controller.handle_command(
            Event(),
            "/source_category animeworldmem news",
        )
        await controller.handle_command(Event(), "/news_fresh_days 2")
        await controller.handle_command(Event(), "/slot 16:00 news anime_news")

        categories = {source.peer: source.category for source in self.state.sources()}
        self.assertEqual(categories["anime_news"], "news")
        self.assertEqual(categories["animeworldmem"], "news")
        self.assertEqual(self.state.get_setting("news_fresh_days"), "2")
        self.assertIn(Slot("16:00", "news", "anime_news"), self.state.slots())

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

    async def test_missed_same_day_slot_is_caught_up_after_late_restart(self):
        controller, publisher = await self.controller()
        item = self.state.enqueue(
            "animeworldmem", "message:18", (18,), "image", 1,
            datetime.now(timezone.utc),
        )

        published = await controller.run_due(
            datetime(2026, 8, 14, 18, 10, tzinfo=controller.timezone)
        )

        self.assertTrue(published)
        self.assertEqual([value.id for value in publisher.calls], [item.id])

    async def test_scheduler_survives_transient_error_and_records_health(self):
        controller, _ = await self.controller()
        calls = 0

        async def run_due():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("temporary Neon error")

        async def sleep(_seconds):
            if calls >= 2:
                raise asyncio.CancelledError

        controller.run_due = run_due
        with self.assertRaises(asyncio.CancelledError):
            await controller.scheduler(sleep=sleep)

        self.assertEqual(calls, 2)
        self.assertIn("temporary Neon error", self.state.get_setting("scheduler_last_error"))
        self.assertIsNotNone(self.state.get_setting("scheduler_heartbeat_at"))

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
        self.assertEqual(self.state.pending_count(), 0)
        self.assertEqual(self.state.pool_items()[0].status, "candidate")

    async def test_rebalance_keeps_top_posts_and_even_source_shares(self):
        now = datetime.now(timezone.utc)
        self.state.add_source("animeworldmem", "Anime World")
        self.state.add_source("source-b", "Source B")
        client = FakeClient({
            "animeworldmem": [
                message(index, views=1000 + index, reactions=index, published_at=now)
                for index in range(1, 7)
            ],
            "source-b": [
                message(100 + index, views=500 + index, reactions=index, published_at=now)
                for index in range(1, 7)
            ],
        })
        controller, _ = await self.controller(client, queue_minimum=4, scan_limit=6)

        await controller.refill(force=True)

        pending = self.state.pending_items(limit=20)
        self.assertEqual(len(pending), 4)
        self.assertEqual({item.source for item in pending}, {"animeworldmem", "source-b"})
        self.assertEqual(
            {item.message_ids[0] for item in pending if item.source == "animeworldmem"},
            {5, 6},
        )

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
