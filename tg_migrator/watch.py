from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass

from telethon import events
from telethon.errors.common import InvalidBufferError

from .automation import AutomationController, HELP as AUTOMATION_HELP
from .config import (
    STATE_FILE,
    AutomationConfig,
    ConfigError,
    Targets,
    load_automation_config,
)
from .max_client import MaxClient, MaxConfig
from .migrator import Progress, TransferMode, migrate_posts
from .publisher import PostPublisher
from .selection import (
    latest_posts,
    parse_start_date,
    post_from_messages,
    posts_from_date,
)
from .state import MigrationState


HELP = """Управление переносом:

/transfer 100 — скопировать последние 100 постов
/transfer_from 01.06.2025 — скопировать посты с даты
/forward 100 — переслать последние 100 с указанием источника
/forward_from 01.06.2025 — переслать с даты
/status — текущий прогресс
/cancel — остановить текущий перенос
/help — показать команды

Команды принимаются только здесь, в «Избранном»."""


@dataclass
class WatchStatus:
    text: str = "Перенос не запущен."


_TRANSIENT_CONNECTION_ERRORS = (
    InvalidBufferError,
    asyncio.IncompleteReadError,
    OSError,
    ConnectionError,
    asyncio.TimeoutError,
)


async def maintain_connection(client, sleep=asyncio.sleep) -> None:
    """Keep the listener alive across temporary Telegram/network failures."""
    retry_delay = 15
    while True:
        try:
            await client.run_until_disconnected()
            retry_delay = 15
        except _TRANSIENT_CONNECTION_ERRORS:
            pass

        try:
            await client.disconnect()
        except Exception:
            pass
        await sleep(retry_delay)
        try:
            await client.connect()
            retry_delay = 15
        except _TRANSIENT_CONNECTION_ERRORS:
            retry_delay = min(retry_delay * 2, 300)


async def _run_legacy_watcher(client, targets: Targets) -> None:
    state = MigrationState(STATE_FILE)
    active_task: asyncio.Task | None = None
    cancel_event: asyncio.Event | None = None
    status = WatchStatus()
    migration_lock = asyncio.Lock()

    async def launch(
        event,
        selector: str,
        value: str,
        mode: TransferMode,
    ) -> None:
        nonlocal active_task, cancel_event
        if active_task is not None and not active_task.done():
            await event.respond(
                "Уже выполняется перенос. Используйте /status или /cancel."
            )
            return

        cancel_event = asyncio.Event()
        status.text = "Читаю историю источника…"
        status_message = await event.respond(status.text)

        async def job() -> None:
            try:
                iterator = client.iter_messages(targets.source)
                if selector == "count":
                    posts = await latest_posts(iterator, int(value))
                else:
                    posts = await posts_from_date(
                        iterator,
                        parse_start_date(value),
                    )
                if not posts:
                    status.text = "Подходящих публикаций не найдено."
                    await status_message.edit(status.text)
                    return

                status.text = f"Найдено публикаций: {len(posts)}. Начинаю."
                await status_message.edit(status.text)

                async def on_progress(progress: Progress) -> None:
                    if (
                        progress.processed_posts % 10 != 0
                        and progress.processed_posts != progress.total_posts
                        and not progress.cancelled
                    ):
                        return
                    if progress.cancelled:
                        status.text = (
                            "Перенос остановлен. "
                            f"Готово: {progress.transferred_posts}, "
                            f"пропущено дублей: {progress.skipped_posts}."
                        )
                    else:
                        status.text = (
                            f"Обработано {progress.processed_posts}/"
                            f"{progress.total_posts}; перенесено "
                            f"{progress.transferred_posts}; дублей "
                            f"{progress.skipped_posts}."
                        )
                    await status_message.edit(status.text)

                async with migration_lock:
                    result = await migrate_posts(
                        client,
                        targets.source,
                        targets.destination,
                        posts,
                        state,
                        mode=mode,
                        cancel_event=cancel_event,
                        callback=on_progress,
                    )
                if not result.cancelled:
                    status.text = (
                        "Готово. "
                        f"Перенесено: {result.transferred_posts}, "
                        f"пропущено дублей: {result.skipped_posts}."
                    )
                    await status_message.edit(status.text)
            except (ValueError, RuntimeError) as exc:
                status.text = f"Ошибка: {exc}"
                await status_message.edit(status.text)
            except Exception as exc:
                status.text = (
                    "Неожиданная ошибка: "
                    f"{exc.__class__.__name__}: {exc}"
                )
                await status_message.edit(status.text)

        active_task = asyncio.create_task(job())

    @client.on(events.NewMessage(chats="me", outgoing=True))
    async def command_handler(event) -> None:
        nonlocal cancel_event
        text = (event.raw_text or "").strip()
        if text == "/help":
            await event.respond(HELP)
            return
        if text == "/status":
            await event.respond(status.text)
            return
        if text == "/cancel":
            if cancel_event is None or active_task is None or active_task.done():
                await event.respond("Активного переноса нет.")
            else:
                cancel_event.set()
                await event.respond("Останавливаю после текущей публикации…")
            return

        match = re.fullmatch(
            r"/(transfer|transfer_from|forward|forward_from)\s+(.+)",
            text,
        )
        if match is None:
            return
        command, value = match.groups()
        selector = "date" if command.endswith("_from") else "count"
        mode = (
            TransferMode.FORWARD
            if command.startswith("forward")
            else TransferMode.COPY
        )
        if selector == "count":
            try:
                count = int(value)
            except ValueError:
                await event.respond("После команды укажите целое число.")
                return
            if count <= 0:
                await event.respond("Количество должно быть больше нуля.")
                return
            value = str(count)
        else:
            try:
                parse_start_date(value)
            except ValueError as exc:
                await event.respond(str(exc))
                return
        await launch(event, selector, value, mode)

    async def auto_transfer(messages) -> None:
        post = post_from_messages(tuple(messages))
        if post is None:
            return
        try:
            async with migration_lock:
                result = await migrate_posts(
                    client,
                    targets.source,
                    targets.destination,
                    [post],
                    state,
                    mode=TransferMode.COPY,
                )
            if result.transferred_posts:
                status.text = (
                    "Автоперенос: новая публикация перенесена "
                    f"(источник #{post.ids[0]})."
                )
        except Exception as exc:
            status.text = f"Ошибка автопереноса: {exc}"
            await client.send_message("me", status.text)

    @client.on(events.Album(chats=targets.source))
    async def album_handler(event) -> None:
        await auto_transfer(event.messages)

    @client.on(events.NewMessage(chats=targets.source))
    async def new_message_handler(event) -> None:
        # Albums are handled atomically by events.Album.
        if getattr(event.message, "grouped_id", None) is not None:
            return
        await auto_transfer([event.message])

    try:
        try:
            await client.send_message(
                "me",
                "Переносчик запущен. Новые публикации будут переноситься "
                "автоматически.\n\n" + HELP,
            )
        except _TRANSIENT_CONNECTION_ERRORS:
            pass
        await maintain_connection(client)
    finally:
        if active_task is not None and not active_task.done():
            if cancel_event is not None:
                cancel_event.set()
            await active_task
        state.close()


async def _run_automation_watcher(
    client,
    targets: Targets,
    config: AutomationConfig,
) -> None:
    if not config.max_token:
        raise ConfigError(
            "Для автоматизации задайте MAX_BOT_TOKEN. "
            "До этого оставьте TG_AUTOMATION_ENABLED=false."
        )
    state = MigrationState(STATE_FILE, config.database_url)
    max_client = MaxClient(
        MaxConfig(
            token=config.max_token,
            channel=config.max_channel,
            api_base=config.max_api_base,
        )
    )
    publisher = PostPublisher(
        client,
        state,
        config.destination,
        max_client,
        default_signature=(config.signature_text, config.signature_url),
    )
    controller = AutomationController(client, state, publisher, config)
    tasks: list[asyncio.Task] = []
    try:
        await controller.initialize()

        @client.on(events.NewMessage())
        async def automation_message_handler(event) -> None:
            if controller.is_authorized(event):
                handled = await controller.handle_command(
                    event,
                    (event.raw_text or "").strip(),
                )
                if handled:
                    return
            if getattr(event.message, "grouped_id", None) is not None:
                return
            await controller.handle_new_post(
                [event.message],
                chat_id=getattr(event, "chat_id", None),
            )

        @client.on(events.Album())
        async def automation_album_handler(event) -> None:
            await controller.handle_new_post(
                event.messages,
                chat_id=getattr(event, "chat_id", None),
            )

        tasks = [
            asyncio.create_task(controller.refill_loop(), name="queue-refill"),
            asyncio.create_task(controller.scheduler(), name="schedule"),
        ]
        await controller.notify(
            "Desiree запущена: очередь и расписание включены.\n\n"
            + AUTOMATION_HELP
        )
        await maintain_connection(client)
    finally:
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await max_client.aclose()
        state.close()


async def run_watcher(
    client,
    targets: Targets,
    automation_config: AutomationConfig | None = None,
) -> None:
    config = automation_config or load_automation_config()
    if config.enabled:
        await _run_automation_watcher(client, targets, config)
    else:
        await _run_legacy_watcher(client, targets)
