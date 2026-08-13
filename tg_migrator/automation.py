from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from telethon import utils
from telethon.errors import UserAlreadyParticipantError
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest

from .config import AutomationConfig, normalize_peer
from .selection import (
    MOSCOW,
    latest_posts,
    parse_start_date,
    post_activity,
    post_from_messages,
    post_media_kind,
    posts_from_date,
)
from .state import MigrationState, QueueItem, Slot


DEFAULT_SLOTS = (
    Slot("08:00", "any"),
    Slot("10:00", "any"),
    Slot("12:00", "any"),
    Slot("14:00", "video"),
    Slot("18:00", "any"),
    Slot("21:00", "any"),
)

HELP = """Управление Desiree:

/add_source ССЫЛКА — добавить источник
/del_source ИСТОЧНИК — удалить источник
/sources — список источников
/parse [КОЛИЧЕСТВО] [ИСТОЧНИК] — наполнить очередь
/parse_from ДАТА [КОЛИЧЕСТВО] — собрать с даты
/parse_period ДАТА ДАТА [КОЛИЧЕСТВО] — собрать за период
/parse_top ДНЕЙ КОЛИЧЕСТВО [ИСТОЧНИК] — самые активные
/transfer КОЛИЧЕСТВО — собрать и опубликовать сейчас
/transfer_from ДАТА — собрать с даты и опубликовать
/queue — состояние очереди
/now [any|video|image] [ИСТОЧНИК] — публикация сейчас
/times [08:00,10:00,...] — показать/заменить расписание
/slot ЧЧ:ММ any|video|image [ИСТОЧНИК] — настроить слот
/unslot ЧЧ:ММ — удалить слот
/signature ТЕКСТ | URL — изменить единственную подпись MAX
/retry ID — повторить ошибку после проверки канала
/status или /config — состояние
/cancel — остановить массовую команду
/help — эта справка

Можно просто прислать публичную ссылку t.me для добавления источника."""

_SOURCE_LINK_RE = re.compile(r"^(?:https?://)?t\.me/(?:joinchat/|\+)?[^\s/]+/?$", re.I)


def _entity_peer_id(entity) -> int:
    try:
        return int(utils.get_peer_id(entity))
    except (TypeError, ValueError):
        return int(entity.id)


def _valid_time(value: str) -> str:
    try:
        return datetime.strptime(value, "%H:%M").strftime("%H:%M")
    except ValueError as exc:
        raise ValueError("Время указывается как ЧЧ:ММ, например 14:00.") from exc


class AutomationController:
    def __init__(
        self,
        client,
        state: MigrationState,
        publisher,
        config: AutomationConfig,
    ):
        self.client = client
        self.state = state
        self.publisher = publisher
        self.config = config
        self.timezone = MOSCOW
        self.account_id: int | None = None
        self._chat_sources: dict[int, str] = {}
        self._cancel = asyncio.Event()

    async def initialize(self) -> None:
        self.account_id = int((await self.client.get_me()).id)
        self.state.recover_interrupted()
        if not self.state.sources():
            await self.add_source(str(self.config.initial_source))
        else:
            for source in self.state.sources():
                try:
                    entity = await self.client.get_entity(source.peer)
                except Exception:
                    continue
                self._chat_sources[_entity_peer_id(entity)] = source.peer
        if not self.state.slots():
            for slot in DEFAULT_SLOTS:
                self.state.set_slot(slot)
        if self.state.get_setting("signature_text") is None:
            self.state.set_setting("signature_text", self.config.signature_text)
        if self.state.get_setting("signature_url") is None:
            self.state.set_setting("signature_url", self.config.signature_url)

    def is_authorized(self, event) -> bool:
        if not getattr(event, "is_private", False):
            return False
        if (
            getattr(event, "outgoing", False)
            and self.account_id is not None
            and int(getattr(event, "chat_id", 0) or 0) == self.account_id
        ):
            return True
        return int(getattr(event, "sender_id", 0) or 0) in self.config.owner_ids

    async def notify(self, text: str) -> None:
        recipients = {"me", *self.config.owner_ids}
        for recipient in recipients:
            try:
                await self.client.send_message(recipient, text)
            except Exception:
                pass

    async def add_source(self, raw: str) -> tuple[str, bool]:
        value = raw.strip()
        entity = None
        invite = re.search(r"(?:joinchat/|t\.me/\+)([^/?]+)", value, re.I)
        if invite:
            result = await self.client(ImportChatInviteRequest(invite.group(1)))
            entity = result.chats[0] if result.chats else None
        else:
            peer = normalize_peer(value)
            try:
                await self.client(JoinChannelRequest(peer))
            except UserAlreadyParticipantError:
                pass
            entity = await self.client.get_entity(peer)
        if entity is None:
            raise ValueError("Telegram не вернул добавленный канал.")
        peer = getattr(entity, "username", None) or str(_entity_peer_id(entity))
        title = getattr(entity, "title", None) or str(peer)
        added = self.state.add_source(str(peer), str(title))
        self._chat_sources[_entity_peer_id(entity)] = str(peer)
        return str(peer), added

    async def remove_source(self, raw: str) -> bool:
        peer = str(normalize_peer(raw))
        removed = self.state.remove_source(peer)
        if removed:
            self._chat_sources = {
                chat_id: source
                for chat_id, source in self._chat_sources.items()
                if source != peer
            }
        return removed

    def _selected_sources(self, raw: str | None = None) -> list[str]:
        available = [source.peer for source in self.state.sources()]
        if raw is None:
            return available
        peer = str(normalize_peer(raw))
        if peer not in available:
            raise ValueError("Такого источника нет. Сначала используйте /add_source.")
        return [peer]

    def _enqueue_posts(self, source: str, posts, limit: int | None = None) -> int:
        added = 0
        for post in posts:
            if self._cancel.is_set():
                break
            item = self.state.enqueue(
                source,
                post.key,
                post.ids,
                post_media_kind(post),
                post_activity(post),
                post.published_at,
            )
            if item is not None:
                added += 1
                if limit is not None and added >= limit:
                    break
        return added

    async def parse_latest(
        self,
        count: int,
        source: str | None = None,
        *,
        required_kind: str = "any",
    ) -> int:
        if count <= 0:
            raise ValueError("Количество должно быть больше нуля.")
        total = 0
        for peer in self._selected_sources(source):
            read_count = self.config.scan_limit if required_kind != "any" else count
            posts = await latest_posts(
                self.client.iter_messages(peer, limit=read_count),
                read_count,
            )
            posts.sort(key=lambda post: (post_activity(post), post.published_at), reverse=True)
            if required_kind != "any":
                posts = [post for post in posts if post_media_kind(post) == required_kind]
            total += self._enqueue_posts(peer, posts, count - total)
            if total >= count or self._cancel.is_set():
                break
        return total

    async def parse_from(
        self,
        start: datetime,
        count: int,
        source: str | None = None,
        end: datetime | None = None,
        top: bool = False,
    ) -> int:
        total = 0
        for peer in self._selected_sources(source):
            posts = await posts_from_date(self.client.iter_messages(peer), start)
            if end is not None:
                posts = [post for post in posts if post.published_at < end]
            if top:
                posts.sort(key=lambda post: (post_activity(post), post.published_at), reverse=True)
            total += self._enqueue_posts(peer, posts, count - total)
            if total >= count or self._cancel.is_set():
                break
        return total

    async def refill(
        self,
        *,
        force: bool = False,
        required_kind: str = "any",
        source: str | None = None,
    ) -> int:
        pending = self.state.pending_count()
        if not force and pending >= self.config.queue_minimum:
            return 0
        wanted = self.config.scan_limit if force else self.config.queue_minimum - pending
        return await self.parse_latest(wanted, source, required_kind=required_kind)

    async def publish_next(
        self,
        kind: str = "any",
        source: str | None = None,
        *,
        refill: bool = True,
    ) -> QueueItem | None:
        source = str(normalize_peer(source)) if source is not None else None
        item = self.state.claim(kind, source)
        if item is None and refill:
            await self.refill(force=True, required_kind=kind, source=source)
            item = self.state.claim(kind, source)
        if item is None:
            return None
        await self.publisher.publish(item)
        return item

    async def handle_new_post(self, messages, *, chat_id: int | None = None) -> bool:
        if not messages:
            return False
        resolved_chat = chat_id
        if resolved_chat is None:
            resolved_chat = getattr(messages[0], "chat_id", None)
        source = self._chat_sources.get(int(resolved_chat or 0))
        if source is None:
            return False
        post = post_from_messages(tuple(messages))
        if post is None:
            return False
        return self._enqueue_posts(source, [post]) == 1

    async def run_due(self, now: datetime | None = None) -> bool:
        current = now or datetime.now(self.timezone)
        run_time = current.strftime("%H:%M")
        slot = next((value for value in self.state.slots() if value.time == run_time), None)
        if slot is None:
            return False
        item = self.state.claim(slot.kind, slot.source)
        if item is None:
            await self.refill(force=True, required_kind=slot.kind, source=slot.source)
            item = self.state.claim(slot.kind, slot.source)
        if item is None:
            await self.notify(f"Слот {run_time}: подходящего поста нет.")
            return False
        if not self.state.claim_slot(current.date(), run_time):
            self.state.release(item.id)
            return False
        try:
            await self.publisher.publish(item)
        except Exception as exc:
            await self.notify(f"Ошибка публикации {item.id}: {exc}")
            return False
        return True

    async def scheduler(self) -> None:
        while True:
            await self.run_due()
            await asyncio.sleep(20)

    async def refill_loop(self) -> None:
        while True:
            try:
                await self.refill()
            except Exception as exc:
                await self.notify(f"Ошибка пополнения очереди: {exc}")
            await asyncio.sleep(self.config.refill_interval)

    async def _respond_queue(self, event) -> None:
        counts = self.state.queue_counts()
        text = ", ".join(f"{key}: {value}" for key, value in sorted(counts.items()))
        await event.respond("Очередь: " + (text or "пуста"))

    async def _parse_command(self, event, command: str, arguments: list[str]) -> None:
        self._cancel.clear()
        if command in {"parse", "transfer", "forward"}:
            count = int(arguments[0]) if arguments else 50
            source = arguments[1] if len(arguments) > 1 else None
            added = await self.parse_latest(count, source)
            published = 0
            if command in {"transfer", "forward"}:
                for _ in range(count):
                    if self._cancel.is_set() or await self.publish_next(refill=False) is None:
                        break
                    published += 1
            await event.respond(f"Добавлено: {added}. Опубликовано: {published}.")
            return
        if command in {"parse_from", "transfer_from", "forward_from"}:
            if not arguments:
                raise ValueError("Укажите дату после команды.")
            start = parse_start_date(arguments[0])
            count = int(arguments[1]) if len(arguments) > 1 else self.config.scan_limit
            added = await self.parse_from(start, count)
            published = 0
            if command != "parse_from":
                for _ in range(count):
                    if self._cancel.is_set() or await self.publish_next(refill=False) is None:
                        break
                    published += 1
            await event.respond(f"Добавлено: {added}. Опубликовано: {published}.")
            return
        if command == "parse_period":
            if len(arguments) < 2:
                raise ValueError("Нужны начальная и конечная даты.")
            start = parse_start_date(arguments[0])
            end = parse_start_date(arguments[1]) + timedelta(days=1)
            count = int(arguments[2]) if len(arguments) > 2 else self.config.scan_limit
            added = await self.parse_from(start, count, end=end)
            await event.respond(f"Добавлено: {added}.")
            return
        if command == "parse_top":
            if len(arguments) < 2:
                raise ValueError("Формат: /parse_top ДНЕЙ КОЛИЧЕСТВО [ИСТОЧНИК].")
            days, count = int(arguments[0]), int(arguments[1])
            source = arguments[2] if len(arguments) > 2 else None
            start = datetime.now(timezone.utc) - timedelta(days=days)
            added = await self.parse_from(start, count, source=source, top=True)
            await event.respond(f"Добавлено активных постов: {added}.")

    async def handle_command(self, event, raw_text: str) -> bool:
        if not self.is_authorized(event):
            return False
        text = raw_text.strip()
        if _SOURCE_LINK_RE.fullmatch(text):
            peer, added = await self.add_source(text)
            await event.respond(
                f"Источник {peer} добавлен." if added else f"Источник {peer} уже есть."
            )
            return True
        if not text.startswith("/"):
            return False
        command, _, tail = text[1:].partition(" ")
        command = command.lower()
        arguments = tail.split() if tail else []
        try:
            if command in {"help", "start"}:
                await event.respond(HELP)
            elif command in {"status", "config"}:
                counts = self.state.queue_counts()
                storage = "Neon" if self.config.database_url else "локальный SQLite"
                await event.respond(
                    f"Desiree: автоматизация включена. Хранилище: {storage}. "
                    f"Источников: {len(self.state.sources())}. Очередь: {counts}."
                )
            elif command == "cancel":
                self._cancel.set()
                await event.respond("Останавливаю после текущей операции.")
            elif command == "sources":
                rows = [f"• {source.title} — {source.peer}" for source in self.state.sources()]
                await event.respond("Источники:\n" + ("\n".join(rows) or "нет"))
            elif command == "add_source":
                if not tail:
                    raise ValueError("Укажите ссылку или @username источника.")
                peer, added = await self.add_source(tail)
                await event.respond(
                    f"Источник {peer} добавлен." if added else f"Источник {peer} уже есть."
                )
            elif command == "del_source":
                if not tail:
                    raise ValueError("Укажите источник для удаления.")
                removed = await self.remove_source(tail)
                await event.respond("Источник удалён." if removed else "Источник не найден.")
            elif command in {
                "parse", "parse_from", "parse_period", "parse_top",
                "transfer", "transfer_from", "forward", "forward_from",
            }:
                await self._parse_command(event, command, arguments)
            elif command == "queue":
                await self._respond_queue(event)
            elif command == "now":
                kind = arguments[0].lower() if arguments else "any"
                if kind not in {"any", "video", "image"}:
                    raise ValueError("Тип публикации: any, video или image.")
                source = arguments[1] if len(arguments) > 1 else None
                item = await self.publish_next(kind, source)
                await event.respond(
                    f"Опубликовано: {item.id}." if item else "Подходящего поста нет."
                )
            elif command == "times":
                if not tail:
                    await event.respond(
                        "Расписание: "
                        + ", ".join(
                            f"{slot.time} {slot.kind}"
                            + (f" {slot.source}" if slot.source else "")
                            for slot in self.state.slots()
                        )
                    )
                else:
                    times = [_valid_time(value.strip()) for value in tail.split(",")]
                    for slot in self.state.slots():
                        self.state.remove_slot(slot.time)
                    for run_time in sorted(set(times)):
                        self.state.set_slot(Slot(run_time))
                    await event.respond("Расписание обновлено.")
            elif command == "slot":
                if len(arguments) < 2:
                    raise ValueError("Формат: /slot ЧЧ:ММ any|video|image [ИСТОЧНИК].")
                run_time, kind = _valid_time(arguments[0]), arguments[1].lower()
                if kind not in {"any", "video", "image"}:
                    raise ValueError("Тип слота: any, video или image.")
                source = str(normalize_peer(arguments[2])) if len(arguments) > 2 else None
                if source and source not in self._selected_sources():
                    raise ValueError("Сначала добавьте источник через /add_source.")
                self.state.set_slot(Slot(run_time, kind, source))
                await event.respond(f"Слот {run_time}: {kind}" + (f", {source}" if source else ""))
            elif command == "unslot":
                if not arguments:
                    raise ValueError("Укажите время слота.")
                removed = self.state.remove_slot(_valid_time(arguments[0]))
                await event.respond("Слот удалён." if removed else "Слот не найден.")
            elif command == "signature":
                if not tail:
                    await event.respond(
                        f"Подпись: {self.state.get_setting('signature_text')} | "
                        f"{self.state.get_setting('signature_url')}"
                    )
                else:
                    parts = [part.strip() for part in tail.rsplit("|", 1)]
                    if len(parts) != 2 or not all(parts):
                        raise ValueError("Формат: /signature ТЕКСТ | https://ссылка")
                    parsed = urlparse(parts[1])
                    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                        raise ValueError("Подпись должна содержать http(s)-ссылку.")
                    self.state.set_setting("signature_text", parts[0])
                    self.state.set_setting("signature_url", parts[1])
                    await event.respond("Подпись MAX обновлена.")
            elif command == "retry":
                if not arguments:
                    raise ValueError("Укажите ID элемента очереди.")
                await event.respond(
                    "Возвращено в очередь." if self.state.retry(arguments[0])
                    else "Элемент с ошибкой не найден."
                )
            else:
                return False
        except (ValueError, RuntimeError) as exc:
            await event.respond(f"Ошибка: {exc}")
        return True
