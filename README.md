# Desiree: Telegram → 2D Web → MAX

Этот репозиторий запускает пользовательский Telegram-аккаунт **Desiree Pez**
(`@aidesigndd`). Он собирает публикации из настраиваемых Telegram-источников,
держит очередь, публикует по московскому расписанию в `@webnmy` (`2D Web`) и
напрямую в MAX-канал `https://max.ru/channel_animenaruto`.

Это не проект аниме-эдитов `animecrooss`: там работает другой reader-аккаунт
«бьянка». Репозитории, сессии и процессы не должны использоваться друг вместо
друга.

## Что умеет новый режим

- добавлять и удалять источники сообщением Desiree;
- вступать в добавляемые публичные Telegram-каналы;
- собирать новые, последние, публикации за период и самые активные;
- считать альбом одной публикацией и не ставить один source post в очередь
  дважды;
- постоянно пополнять очередь;
- настраивать время, тип `any`/`video`/`image` и источник каждого слота;
- сохранять обычный текст и Telegram-форматирование;
- удалять из источника видимые URL, скрытые ссылки, `@username`, рекламные
  строки и осиротевшие рекламные эмодзи;
- добавлять в MAX ровно одну изменяемую подпись — по умолчанию
  [НАШ ТГК](https://t.me/webm4ik);
- скачивать медиа пользовательской сессией Telethon, поэтому видео больше
  20 МБ не упираются в ограничение Telegram Bot API;
- хранить настройки, очередь, расписание и дедупликацию в Neon/PostgreSQL.

## Команды

Команды принимаются в «Избранном» Desiree и во входящем личном чате от ID из
`TG_OWNER_IDS` (по умолчанию `8235497168`).

```text
/add_source https://t.me/animeworldmem
/del_source animeworldmem
/sources

/parse 50
/parse 50 animeworldmem
/parse_from 01.08.2026 100
/parse_period 01.08.2026 10.08.2026 100
/parse_top 30 50 animeworldmem
/queue

/transfer 10
/transfer_from 01.08.2026 10
/now any
/now video animeworldmem

/times
/times 08:00,10:00,12:00,14:00,18:00,21:00
/slot 14:00 video animeworldmem
/slot 18:00 any
/unslot 10:00

/signature
/signature НАШ ТГК | https://t.me/webm4ik
/retry ID
/status
/config
/cancel
/help
```

Публичную ссылку `https://t.me/...` можно прислать без команды — она будет
добавлена как источник. `/parse` только наполняет очередь. `/transfer` и
`/now` публикуют немедленно и не отмечают слот расписания выполненным.

Начальное расписание в `Europe/Moscow`:

```text
08:00 any
10:00 any
12:00 any
14:00 video
18:00 any
21:00 any
```

## Защита от повторов

Очередь уникальна по Telegram-источнику и ID сообщения/альбома. Публикация
проходит два отдельно сохранённых этапа:

1. очищенная копия появляется в `@webnmy`, её ID сохраняется;
2. оригинальное медиа скачивается через Telethon и отправляется MAX-ботом.

Если процесс перезапустился после сохранённого Telegram-этапа, он продолжит с
MAX и не повторит пост в `@webnmy`. Если соединение оборвалось именно во время
POST в MAX, элемент становится `ambiguous`: автоматического повтора нет, чтобы
не сделать дубль. После ручной проверки канала владелец может выполнить
`/retry ID`.

## Локальный запуск

Требуется Python 3.11 или новее:

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/tg-migrator configure-targets \
  --source https://t.me/animeworldmem \
  --destination https://t.me/webnmy
.venv/bin/tg-migrator configure-secrets
.venv/bin/tg-migrator auth
.venv/bin/tg-migrator watch
```

Старые CLI-команды `count`, `from-date`, `verify`, `install-service` и
`service-status` сохранены. При `TG_AUTOMATION_ENABLED=false` watcher также
сохраняет прежнее поведение: один источник автоматически копируется в один
Telegram-канал без прямой MAX-публикации.

## Переменные Render

Для нового Telegram-аккаунта на macOS не нужно добавлять переменные
по одной. Снача сбросьте пароль Neon, если прежняя строка
подключения была опубликована, затем запустите:

```bash
python3 -m tg_migrator prepare-render
```

Номер, код Telegram, 2FA, новая строка Neon и MAX-токен вводятся
скрыто. Команда создаёт отдельную StringSession только в памяти,
не трогает сессию Desiree и копирует готовый блок в буфер. В
Render нажмите **Add from .env** и вставьте блок целиком. В нём
`TG_AUTOMATION_ENABLED=false`; менять на `true` можно только после
проверки нового аккаунта и отключения старого MAX-реле.

Секреты не находятся в Git. Существующие Telegram-секреты остаются в
Environment текущего Render-сервиса.

| Переменная | Назначение |
| --- | --- |
| `TG_API_ID`, `TG_API_HASH`, `TG_PHONE` | существующие данные Telegram API |
| `TG_SESSION_STRING` | существующая сессия Desiree Pez |
| `TG_AUTOMATION_ENABLED` | `false` для безопасного первого деплоя, затем `true` |
| `TG_OWNER_IDS` | Telegram ID владельцев через запятую |
| `TG_DESTINATION` | `webnmy` |
| `TG_INITIAL_SOURCE` | `animeworldmem` |
| `DATABASE_URL` | строка подключения Neon/PostgreSQL |
| `MAX_BOT_TOKEN` | токен уже созданного MAX-бота |
| `MAX_CHANNEL` | числовой `chat_id`; для текущего канала `-77809668353385` |
| `MAX_SIGNATURE_TEXT` | начальный текст `НАШ ТГК` |
| `MAX_SIGNATURE_URL` | начальная ссылка `https://t.me/webm4ik` |
| `TG_QUEUE_MINIMUM` | минимальный запас, по умолчанию `18` |
| `TG_REFILL_INTERVAL` | период сканирования, по умолчанию `900` секунд |
| `TG_SCAN_LIMIT` | глубина сканирования, по умолчанию `120` |
| `TG_FRESH_DAYS` | окно свежести умного отбора, по умолчанию `7` дней |
| `TG_TARGET_SCAN_LIMIT` | история `@webnmy` для защиты первого запуска, по умолчанию `1000` |

Перед публикацией Desiree обновляет реакции, пересылки и просмотры у
кандидатов, чередует источники и выбирает пост из пяти лучших с весом в
пользу лидера. Команда `/fresh_days 14` меняет окно свежести без деплоя.

MAX API принимает числовой `chat_id`. Для публичной ссылки
`https://max.ru/channel_animenaruto` текущий Bot API ID — `-77809668353385`.

## Безопасное переключение на Render

1. Задеплоить новый commit с `TG_AUTOMATION_ENABLED=false`. Это сохраняет
   прежний перенос и не запускает второй MAX-публикатор.
2. Убедиться в логах, что авторизован именно Desiree Pez, а health URL отвечает
   `tg-migrator: ok`.
3. Добавить в сервис `cross` значения `DATABASE_URL` из Neon и
   `MAX_BOT_TOKEN` старого MAX-публикатора. Установить
   `MAX_CHANNEL=-77809668353385`.
4. Остановить старый сервис `telegram-max-crossposter`, который слушает
   `@webnmy`. Иначе старый relay и новый прямой publisher могут сделать дубль.
5. Поставить `TG_AUTOMATION_ENABLED=true` и перезапустить `cross`.
6. В личном чате Desiree выполнить `/status`, `/sources`, `/times`, затем
   `/parse 1` и `/now any`. Проверить одну публикацию в `@webnmy` и новом MAX.
7. При ошибке вернуть `TG_AUTOMATION_ENABLED=false` до выяснения причины и
   снова включить старый relay.

На бесплатном Render локальный диск временный, поэтому для рабочего режима
нужен `DATABASE_URL`. Также нужен внешний HTTP-пинг health URL каждые 5–10
минут: без него Free Web Service засыпает и не сможет точно выдерживать слоты.

Не запускайте одну и ту же `TG_SESSION_STRING` одновременно локально и на
Render — Telegram может разорвать соединения обоих процессов.
