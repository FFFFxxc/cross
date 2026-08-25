import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from tg_migrator.post_metadata import caption_excerpt, post_metrics
from tg_migrator.selection import (
    Post,
    latest_posts,
    parse_start_date,
    post_activity,
    post_fingerprint,
    post_from_messages,
    post_media_kind,
    post_smart_score,
    posts_from_date,
    sanitize_message_text,
)


def message(
    message_id,
    day,
    text="post",
    grouped_id=None,
    action=None,
    entities=None,
    media=None,
    photo=None,
    video=None,
    views=0,
    forwards=0,
    reactions=None,
):
    return SimpleNamespace(
        id=message_id,
        date=datetime(2025, 6, day, 12, tzinfo=timezone.utc),
        message=text,
        raw_text=text,
        media=media,
        photo=photo,
        video=video,
        grouped_id=grouped_id,
        action=action,
        entities=entities,
        views=views,
        forwards=forwards,
        reactions=reactions,
    )


async def iterator(items):
    for item in items:
        yield item


class SelectionTests(unittest.IsolatedAsyncioTestCase):
    def test_post_metrics_sum_album_counters_and_caption_is_bounded(self):
        first = message(
            1,
            1,
            text="а" * 20,
            views=1_000,
            forwards=7,
            reactions=SimpleNamespace(
                results=[SimpleNamespace(count=30), SimpleNamespace(count=15)]
            ),
        )
        second = message(
            2,
            1,
            text="вторая подпись",
            grouped_id=9,
            views=2_000,
            forwards=13,
            reactions=SimpleNamespace(results=[SimpleNamespace(count=30)]),
        )
        first.grouped_id = 9
        post = post_from_messages((first, second))

        self.assertEqual(post_metrics(post).views, 3_000)
        self.assertEqual(post_metrics(post).reactions, 75)
        self.assertEqual(post_metrics(post).forwards, 20)
        self.assertEqual(caption_excerpt(post, limit=10), "а" * 9 + "…")

    def test_post_metrics_treat_missing_telegram_counters_as_zero(self):
        post = Post(
            "message:1",
            (SimpleNamespace(id=1, date=datetime.now(timezone.utc), raw_text=""),),
        )

        self.assertEqual(post_metrics(post).views, 0)
        self.assertEqual(post_metrics(post).reactions, 0)
        self.assertEqual(post_metrics(post).forwards, 0)
        self.assertEqual(caption_excerpt(post), "")

    def test_sanitizer_removes_every_foreign_link_line(self):
        text = (
            "Обычный текст\n"
            "📢 ХОТ КОНТЕНТ (https://t.me/fulli4k_bot)\n"
            "Мы в MAX: https://max.ru/channel_anime2d"
        )

        cleaned, entities = sanitize_message_text(text, [])

        self.assertEqual(cleaned, "Обычный текст")
        self.assertEqual(entities, [])

    def test_sanitizer_removes_hidden_link_and_username_lines(self):
        text = "Жирный текст\nНАЖМИ СЮДА\nАвтор: @foreign_channel"
        prefix = "Жирный текст\n"
        hidden = SimpleNamespace(
            offset=len(prefix.encode("utf-16-le")) // 2,
            length=len("НАЖМИ СЮДА".encode("utf-16-le")) // 2,
            url="https://bad.example",
        )
        bold = SimpleNamespace(
            offset=0,
            length=len("Жирный".encode("utf-16-le")) // 2,
        )

        cleaned, entities = sanitize_message_text(text, [bold, hidden])

        self.assertEqual(cleaned, "Жирный текст")
        self.assertEqual(len(entities), 1)
        self.assertEqual(entities[0].offset, 0)
        self.assertEqual(entities[0].length, 6)

    def test_sanitizer_shifts_entity_offsets_after_removed_prefix(self):
        text = "Мы в Максе: 🙂 жирный текст"
        prefix = "Мы в Максе: 🙂 "
        entity = SimpleNamespace(
            offset=len(prefix.encode("utf-16-le")) // 2,
            length=len("жирный".encode("utf-16-le")) // 2,
        )

        cleaned, entities = sanitize_message_text(text, [entity])

        self.assertEqual(cleaned, "🙂 жирный текст")
        self.assertEqual(entities[0].offset, len("🙂 ".encode("utf-16-le")) // 2)
        self.assertEqual(entities[0].length, len("жирный".encode("utf-16-le")) // 2)

    def test_sanitizer_removes_promo_only_lines(self):
        text = "👀 ХОТ КОНТЕНТ\n🥵 МЫ В МАКСЕ"

        cleaned, entities = sanitize_message_text(text, [])

        self.assertEqual(cleaned, "")
        self.assertEqual(entities, [])

    def test_sanitizer_removes_orphan_emoji_after_promo(self):
        cleaned, _ = sanitize_message_text("Текст\n🥵\nФУЛЛ В КАНАЛЕ", [])
        self.assertEqual(cleaned, "Текст")

    async def test_latest_counts_album_as_one_post_and_orders_oldest_first(self):
        items = [
            message(5, 5),
            message(4, 4, grouped_id=10),
            message(3, 4, grouped_id=10),
            message(2, 2),
        ]
        posts = await latest_posts(iterator(items), 2)
        self.assertEqual([post.ids for post in posts], [(3, 4), (5,)])

    async def test_latest_ignores_service_messages(self):
        items = [
            message(3, 3, action=object()),
            message(2, 2),
            message(1, 1),
        ]
        posts = await latest_posts(iterator(items), 2)
        self.assertEqual([post.ids for post in posts], [(1,), (2,)])

    async def test_linked_posts_remain_eligible_for_cleaning(self):
        items = [
            message(4, 4, text="реклама https://bad.example"),
            message(3, 3, text="📢 ХОТ КОНТЕНТ (https://t.me/fulli4k_bot)"),
            message(
                2,
                2,
                text="реклама",
                entities=[
                    type(
                        "TextUrl",
                        (),
                        {"url": "https://bad.example/hidden"},
                    )()
                ],
            ),
            message(1, 1, text="обычный пост"),
        ]
        posts = await latest_posts(iterator(items), 4)
        self.assertEqual([post.ids for post in posts], [(1,), (2,), (3,), (4,)])

    async def test_exact_max_channel_link_is_allowed(self):
        items = [
            message(
                2,
                2,
                text=(
                    "📢 ХОТ КОНТЕНТ https://t.me/fulli4k_bot "
                    "https://max.ru/channel_anime2d"
                ),
            ),
            message(1, 1, text="обычный пост"),
        ]
        posts = await latest_posts(iterator(items), 2)
        self.assertEqual([post.ids for post in posts], [(1,), (2,)])

    async def test_link_in_album_does_not_drop_media(self):
        items = [
            message(4, 4, text="подпись", grouped_id=8),
            message(3, 4, text="https://bad.example", grouped_id=8),
            message(2, 2),
        ]
        posts = await latest_posts(iterator(items), 2)
        self.assertEqual([post.ids for post in posts], [(2,), (3, 4)])

    async def test_from_date_is_inclusive_and_chronological(self):
        items = [message(3, 3), message(2, 2), message(1, 1)]
        start = datetime(2025, 6, 2, tzinfo=timezone.utc)
        posts = await posts_from_date(iterator(items), start)
        self.assertEqual([post.ids for post in posts], [(2,), (3,)])

    def test_russian_date_uses_moscow_midnight(self):
        parsed = parse_start_date("02.06.2025")
        self.assertEqual(
            parsed,
            datetime(2025, 6, 1, 21, tzinfo=timezone.utc),
        )

    def test_post_media_kind_prefers_video_in_mixed_album(self):
        post = Post(
            "album:1",
            (
                message(1, 1, media=object(), photo=object()),
                message(2, 1, media=object(), video=object()),
            ),
        )
        self.assertEqual(post_media_kind(post), "video")
        self.assertEqual(
            post_media_kind(Post("message:3", (message(3, 1, media=object(), photo=object()),))),
            "image",
        )
        self.assertEqual(post_media_kind(Post("message:4", (message(4, 1),))), "any")

    def test_post_activity_combines_views_forwards_and_reactions(self):
        reactions = SimpleNamespace(
            results=[SimpleNamespace(count=4), SimpleNamespace(count=2)]
        )
        post = Post(
            "message:1",
            (
                message(
                    1,
                    1,
                    views=100,
                    forwards=3,
                    reactions=reactions,
                ),
            ),
        )
        self.assertEqual(post_activity(post), 139)

    def test_smart_score_decays_equally_active_older_post(self):
        now = datetime(2025, 6, 10, 12, tzinfo=timezone.utc)
        reactions = SimpleNamespace(results=[SimpleNamespace(count=20)])
        fresh = Post(
            "message:1",
            (message(1, 9, views=1_000, reactions=reactions),),
        )
        older = Post(
            "message:2",
            (message(2, 3, views=1_000, reactions=reactions),),
        )

        self.assertGreater(
            post_smart_score(fresh, now),
            post_smart_score(older, now),
        )

    def test_media_fingerprint_is_stable_across_message_ids_and_captions(self):
        first = message(1, 1, text="первая подпись", media=object(), video=object())
        second = message(9, 2, text="другая подпись", media=object(), video=object())
        first.document = SimpleNamespace(id=777, mime_type="video/mp4")
        second.document = SimpleNamespace(id=777, mime_type="video/mp4")

        self.assertEqual(
            post_fingerprint(Post("message:1", (first,))),
            post_fingerprint(Post("message:9", (second,))),
        )


if __name__ == "__main__":
    unittest.main()
