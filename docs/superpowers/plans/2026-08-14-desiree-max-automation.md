# Desiree MAX Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Превратить Desiree Pez в управляемый через Telegram планировщик, который собирает уникальные посты из настраиваемых источников и публикует очищенные медиа в `@webnmy` и новый MAX-канал, включая видео больше 20 МБ.

**Architecture:** Существующий Telethon watcher остаётся единственным процессом. Расширенный SQL store хранит источники, настройки, очередь и этапы доставки в SQLite или Neon; `AutomationController` связывает команды, сканер и планировщик; отдельные `PostPublisher` и `MaxClient` отвечают за двухэтапную отправку и MAX API.

**Tech Stack:** Python 3.11+, Telethon 1.44, SQLAlchemy 2, psycopg 3, HTTPX, pytest/unittest, Docker, Render Free, Neon PostgreSQL.

## Global Constraints

- Изменять только `typonik1/cross`; `animecrooss` не трогать.
- Команды принимает Desiree Pez в «Избранном» и от `TG_OWNER_IDS`, включая `8235497168`.
- Начальный источник — `https://t.me/animeworldmem`.
- Начальные слоты Europe/Moscow: `08:00 any`, `10:00 any`, `12:00 any`, `14:00 video`, `18:00 any`, `21:00 any`.
- Из исходной подписи удалять любые URL, скрытые ссылки, `@username`, рекламные строки и осиротевшие эмодзи.
- В MAX добавлять ровно один изменяемый футер, по умолчанию `НАШ ТГК | https://t.me/webm4ik`.
- MAX-канал по умолчанию: `channel_animenaruto`.
- Не загружать Telegram-медиа через Bot API; использовать Telethon и временные файлы.
- Не повторять `ambiguous` MAX-отправку автоматически.
- Новый режим включать только через `TG_AUTOMATION_ENABLED=true`.

---

### Task 1: Durable store and configuration

**Files:**
- Modify: `pyproject.toml`
- Modify: `tg_migrator/config.py`
- Modify: `tg_migrator/state.py`
- Test: `tests/test_state.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `AutomationConfig`, `load_automation_config()`.
- Produces: `Source`, `Slot`, `QueueItem`, and expanded `MigrationState` methods `add_source`, `remove_source`, `sources`, `get_setting`, `set_setting`, `slots`, `set_slot`, `remove_slot`, `enqueue`, `claim`, `save_telegram_delivery`, `complete`, `mark_error`, `retry`, `queue_counts`, `recover_interrupted`, `claim_slot`.

- [ ] **Step 1: Write failing configuration and store tests.** Assert literal defaults, owner parsing, source uniqueness, slot replacement, queue uniqueness, kind/source claims, published completion, ambiguous blocking, retry, and interrupted recovery.
- [ ] **Step 2: Run `pytest tests/test_state.py tests/test_config.py -q`.** Confirm failures are missing interfaces/defaults.
- [ ] **Step 3: Add dependencies and minimal implementation.** Use SQLAlchemy text DDL compatible with SQLite/PostgreSQL; generate queue UUIDs in Python; store JSON fields as text; use `DATABASE_URL` when present and the existing state file otherwise.
- [ ] **Step 4: Re-run focused and full tests.** Expect focused tests and the original 18 tests to pass.
- [ ] **Step 5: Commit.** Stage only configuration, state, dependency, and corresponding tests.

### Task 2: Clean selection, media typing, and activity ranking

**Files:**
- Modify: `tg_migrator/selection.py`
- Modify: `tests/test_selection.py`

**Interfaces:**
- Produces: `sanitize_message_text(text, entities) -> tuple[str, list]` with all foreign links removed.
- Produces: `post_media_kind(post) -> str` and `post_activity(post) -> int`.
- Produces: `collect_posts(messages, *, start=None, end=None) -> list[Post]` used by newest and top scans.

- [ ] **Step 1: Write failing sanitizer tests.** Cover visible inline URLs, hidden text links, `@username`, promo/footer lines, orphan emoji lines, UTF-16 entity shifting, and retention of bold/italic ordinary text.
- [ ] **Step 2: Write failing classification tests.** Hand-build video, photo, album, reaction/view/forward fixtures and assert literal kinds/scores.
- [ ] **Step 3: Run focused tests and confirm expected failures.** Existing behavior currently allows two links and filters linked posts instead of cleaning them.
- [ ] **Step 4: Implement span/line removal, classification, score, and date collection.** Keep albums atomic and chronological collection deterministic.
- [ ] **Step 5: Run focused/full tests and commit.** Update superseded old expectations to the approved one-signature rule.

### Task 3: Streaming MAX API client

**Files:**
- Create: `tg_migrator/max_client.py`
- Create: `certs/russian-trusted-root-ca.pem`
- Create: `tests/test_max_client.py`

**Interfaces:**
- Produces: `MaxConfig`, `MaxAttachment`, `MaxClient.resolve_channel() -> int`, `MaxClient.upload(path, kind) -> MaxAttachment`, `MaxClient.send(text_html, attachments) -> str`.
- Produces: `MaxApiError`, `AmbiguousMaxSendError`.

- [ ] **Step 1: Write failing HTTP boundary tests.** Verify `/chats/channel_animenaruto`, streamed multipart upload, image/token payloads, `attachment.not.ready` retry, and exact extraction of `message.body.mid`.
- [ ] **Step 2: Run tests and confirm module/interface failures.**
- [ ] **Step 3: Implement the async HTTPX client.** Use `Authorization`, `platform-api2.max.ru`, a trust store containing system/certifi roots plus the required Russian root, bounded timeouts, and no whole-file read into memory.
- [ ] **Step 4: Mark request failures during POST `/messages` ambiguous.** Upload and resolve failures remain retryable because no message submission occurred.
- [ ] **Step 5: Run focused/full tests and commit.**

### Task 4: Two-stage publisher and restart safety

**Files:**
- Create: `tg_migrator/publisher.py`
- Create: `tests/test_publisher.py`

**Interfaces:**
- Consumes: queue/store and MAX client interfaces from Tasks 1 and 3.
- Produces: `PostPublisher.publish(item) -> PublishResult` and `telegram_entities_to_max_html(text, entities) -> str`.

- [ ] **Step 1: Write failing formatting tests.** Assert escaped HTML and supported bold/italic/underline/strike/code entities with correct UTF-16 offsets; assert foreign links never become anchors.
- [ ] **Step 2: Write failing delivery tests.** Assert Telegram clean-copy stage persists Telegram IDs before MAX, restart skips the saved Telegram stage, files larger than 20 MB travel through `client.download_media(file=path)`, success records MAX mid, and ambiguous send blocks retry.
- [ ] **Step 3: Run tests and confirm missing publisher behavior.**
- [ ] **Step 4: Implement minimal publisher.** Fetch original IDs from the saved source, copy/edit to `@webnmy`, download each MAX attachment into `TemporaryDirectory`, upload sequentially to cap memory, append exactly one signature, and update state after each boundary.
- [ ] **Step 5: Run focused/full tests and commit.**

### Task 5: Sources, queue commands, scheduler, and automatic refill

**Files:**
- Create: `tg_migrator/automation.py`
- Modify: `tg_migrator/watch.py`
- Modify: `tg_migrator/__main__.py`
- Test: `tests/test_automation.py`
- Modify: `tests/test_watch.py`

**Interfaces:**
- Consumes: `MigrationState`, selection, and `PostPublisher`.
- Produces: `AutomationController.start()`, `handle_command(event, text) -> bool`, `handle_new_post(messages)`, `refill()`, `scheduler()`.

- [ ] **Step 1: Write failing owner/source tests.** Assert Saved Messages and configured owner are authorized, strangers are ignored, bare `t.me` links add/join sources, and duplicate sources are reported without duplicate rows.
- [ ] **Step 2: Write failing command tests.** Cover `/sources`, `/parse`, period/top parsing, `/queue`, `/times`, typed/source slot changes, `/signature`, `/now`, `/retry`, and compatibility routing for `/transfer`/`/transfer_from`.
- [ ] **Step 3: Write failing scheduler/refill tests.** Assert one run per Moscow slot, `14:00` only claims video, source-specific slots filter correctly, `/now` does not consume a slot marker, and refill stops at the queue minimum.
- [ ] **Step 4: Run focused tests and confirm missing controller behavior.**
- [ ] **Step 5: Implement controller and integrate conditionally.** If `TG_AUTOMATION_ENABLED` is false, preserve the legacy watcher exactly; if true, register authorized command/listener behavior and run refill/scheduler background tasks.
- [ ] **Step 6: Run focused/full tests and commit.**

### Task 6: Render contract, operator documentation, and release verification

**Files:**
- Modify: `README.md`
- Modify: `Dockerfile`
- Create: `render.yaml`
- Test: `tests/test_health.py` only if health output changes.

**Interfaces:**
- Documents exact environment variables and safe cutover order.
- Produces an image that runs `tg-migrator watch` and serves `/health` on `$PORT`.

- [ ] **Step 1: Update README with the Desiree/Бьянка boundary, complete command reference, Neon setup, MAX channel resolution, and >20 MB path.**
- [ ] **Step 2: Add Render Blueprint defaults without secrets.** Include `TG_AUTOMATION_ENABLED=false`, `MAX_CHANNEL=channel_animenaruto`, and secret placeholders for `DATABASE_URL`/`MAX_BOT_TOKEN`.
- [ ] **Step 3: Run `pytest -q`, `python -m compileall -q tg_migrator tests`, and build the Docker image.**
- [ ] **Step 4: Review `git diff --check`, status, and commit history.** Confirm no secrets, `.data`, session, `.env`, `sources/`, anime files, or generated egg-info changes are staged.
- [ ] **Step 5: Warn before deployment.** Explain that pushing `main` may auto-deploy Render; deploy first with automation disabled.
- [ ] **Step 6: Push, verify health/log identity, configure Neon/MAX secrets, suspend the old relay, enable automation, and run a one-post smoke.** If smoke fails, return to legacy mode before retrying.
