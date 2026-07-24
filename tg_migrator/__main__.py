from __future__ import annotations

import argparse
import asyncio
import sys

from .config import (
    ConfigError,
    STATE_FILE,
    configure_credentials,
    load_credentials,
    load_targets,
    save_targets,
)
from .health import maybe_start_health_server
from .migrator import Progress, TransferMode, migrate_posts
from .selection import latest_posts, parse_start_date, posts_from_date
from .service import install_service, service_status, uninstall_service
from .state import MigrationState
from .telegram import authorize, build_client, session_to_string
from .watch import run_watcher


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tg-migrator",
        description="Перенос публикаций между Telegram-чатами.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    targets = subparsers.add_parser("configure-targets")
    targets.add_argument("--source", required=True)
    targets.add_argument("--destination", required=True)

    subparsers.add_parser("configure-secrets")
    subparsers.add_parser("auth")
    export = subparsers.add_parser(
        "export-session",
        help="Напечатать строку сессии (StringSession) для серверов "
        "без диска, например Hugging Face Spaces.",
    )
    export.add_argument(
        "--new",
        action="store_true",
        help="Создать отдельную новую сессию (потребуется вход с кодом), "
        "не трогая локальную файловую сессию.",
    )
    subparsers.add_parser("verify")
    subparsers.add_parser("watch")
    subparsers.add_parser("install-service")
    subparsers.add_parser("uninstall-service")
    subparsers.add_parser("service-status")

    for name in ("count", "from-date"):
        transfer = subparsers.add_parser(name)
        transfer.add_argument("value")
        transfer.add_argument(
            "--mode",
            choices=[mode.value for mode in TransferMode],
            default=TransferMode.COPY.value,
        )
        transfer.add_argument("--dry-run", action="store_true")
    return parser


def _chat_name(entity) -> str:
    return (
        getattr(entity, "title", None)
        or getattr(entity, "username", None)
        or str(getattr(entity, "id", "неизвестный чат"))
    )


async def _run_connected(args) -> None:
    credentials = load_credentials()
    client = build_client(
        credentials,
        fresh_string_session=getattr(args, "new", False),
    )
    await authorize(client, credentials)
    try:
        if args.command == "auth":
            me = await client.get_me()
            print(f"Авторизация выполнена: {me.first_name} (id {me.id}).")
            return

        if args.command == "export-session":
            me = await client.get_me()
            print(
                f"Строка сессии для аккаунта {me.first_name} (id {me.id}).\n"
                "Никому её не передавайте: она даёт полный доступ "
                "к аккаунту.\n",
                file=sys.stderr,
            )
            print(session_to_string(client))
            return

        targets = load_targets()
        source = await client.get_entity(targets.source)
        destination = await client.get_entity(targets.destination)

        if args.command == "verify":
            sample = await client.get_messages(source, limit=1)
            if not sample:
                print("Источник доступен, но история пуста.")
            else:
                print("Источник и его история доступны.")
            print(f"Источник: {_chat_name(source)}")
            print(f"Назначение: {_chat_name(destination)}")
            return

        if args.command == "watch":
            maybe_start_health_server()
            await run_watcher(client, targets)
            return

        iterator = client.iter_messages(source)
        if args.command == "count":
            try:
                count = int(args.value)
            except ValueError as exc:
                raise ConfigError("Количество должно быть целым числом.") from exc
            posts = await latest_posts(iterator, count)
        else:
            posts = await posts_from_date(
                iterator,
                parse_start_date(args.value),
            )

        print(f"Найдено публикаций: {len(posts)}.")
        state = MigrationState(STATE_FILE)

        async def progress(value: Progress) -> None:
            if (
                value.processed_posts % 10 == 0
                or value.processed_posts == value.total_posts
            ):
                print(
                    f"Обработано {value.processed_posts}/"
                    f"{value.total_posts}; перенесено "
                    f"{value.transferred_posts}; дублей "
                    f"{value.skipped_posts}."
                )

        try:
            result = await migrate_posts(
                client,
                source,
                destination,
                posts,
                state,
                mode=TransferMode(args.mode),
                dry_run=args.dry_run,
                callback=progress,
            )
        finally:
            state.close()
        if args.dry_run:
            print(
                "Проверка завершена, сообщения не отправлялись. "
                f"К переносу: {result.transferred_posts}."
            )
        else:
            print(
                f"Готово. Перенесено: {result.transferred_posts}; "
                f"пропущено дублей: {result.skipped_posts}."
            )
    finally:
        await client.disconnect()


def main() -> None:
    args = _parser().parse_args()
    try:
        if args.command == "configure-targets":
            targets = save_targets(args.source, args.destination)
            print(
                "Чаты сохранены: "
                f"{targets.source} → {targets.destination}."
            )
            return
        if args.command == "configure-secrets":
            configure_credentials()
            print("Данные сохранены в защищённом хранилище macOS Keychain.")
            return
        if args.command == "install-service":
            install_service()
            print("Автозапуск установлен: переносчик будет запускаться сам.")
            return
        if args.command == "uninstall-service":
            uninstall_service()
            print("Автозапуск отключён.")
            return
        if args.command == "service-status":
            print(service_status())
            return
        asyncio.run(_run_connected(args))
    except (ConfigError, ValueError, RuntimeError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    except KeyboardInterrupt:
        print("\nОстановлено пользователем.", file=sys.stderr)
        raise SystemExit(130)


if __name__ == "__main__":
    main()
