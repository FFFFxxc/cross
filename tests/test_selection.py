import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from tg_migrator.selection import (
    latest_posts,
    parse_start_date,
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
):
    return SimpleNamespace(
        id=message_id,
        date=datetime(2025, 6, day, 12, tzinfo=timezone.utc),
        message=text,
        raw_text=text,
        media=None,
        grouped_id=grouped_id,
        action=action,
        entities=entities,
    )


async def iterator(items):
    for item in items:
        yield item


class SelectionTests(unittest.IsolatedAsyncioTestCase):
    def test_sanitizer_removes_max_link_and_phrase_but_keeps_telegram_link(self):
        text = (
            "📢 ХОТ КОНТЕНТ (https://t.me/fulli4k_bot) "
            "Мы в MAX: https://max.ru/channel_anime2d"
        )

        cleaned, entities = sanitize_message_text(text, [])

        self.assertEqual(cleaned, "📢 ХОТ КОНТЕНТ (https://t.me/fulli4k_bot)")
        self.assertEqual(entities, [])

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

    async def test_links_are_filtered_but_allowed_bot_link_is_kept(self):
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
        posts = await latest_posts(iterator(items), 2)
        self.assertEqual([post.ids for post in posts], [(1,), (3,)])

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

    async def test_link_in_any_album_item_filters_the_whole_album(self):
        items = [
            message(4, 4, text="подпись", grouped_id=8),
            message(3, 4, text="https://bad.example", grouped_id=8),
            message(2, 2),
        ]
        posts = await latest_posts(iterator(items), 2)
        self.assertEqual([post.ids for post in posts], [(2,)])

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


if __name__ == "__main__":
    unittest.main()
