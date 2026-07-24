---
title: tg-migrator
emoji: 📮
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# Перенос публикаций Telegram

Приложение переносит публикации из закрытой группы или канала в другой
Telegram-чат. Оно умеет выбирать последние N публикаций или публикации с
указанной даты, сохранять альбомы и форматирование, вести прогресс и не
публиковать уже перенесённые сообщения повторно. Публикации со ссылками
отфильтровываются; разрешена только ссылка
`https://t.me/fulli4k_bot`.

## Безопасность

- `api_id`, `api_hash` и номер телефона хранятся в macOS Keychain, а не в
  файлах проекта. На серверах без Keychain те же значения передаются
  переменными окружения: `TG_API_ID`, `TG_API_HASH`, `TG_PHONE`, а сессия —
  строкой `TG_SESSION_STRING` (см. раздел про Hugging Face Spaces).
- Telegram-сессия и журнал переноса находятся в закрытой папке `.data/`,
  которая исключена из Git.
- Команды в Telegram принимаются только из «Избранного» авторизованного
  аккаунта.

## Подготовка

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/tg-migrator configure-targets \
  --source -1000000000000 \
  --destination https://t.me/example
.venv/bin/tg-migrator configure-secrets
.venv/bin/tg-migrator auth
.venv/bin/tg-migrator verify
```

При первом входе Telegram отправит код подтверждения. Если включена
двухэтапная защита, приложение также запросит пароль.

## Разовый перенос

```bash
# Только проверить выборку, ничего не публиковать
.venv/bin/tg-migrator count 100 --dry-run

# Скопировать последние 100 публикаций без плашки «Переслано»
.venv/bin/tg-migrator count 100

# Скопировать публикации с даты
.venv/bin/tg-migrator from-date 01.06.2025

# Переслать с сохранением указания исходного чата
.venv/bin/tg-migrator count 100 --mode forward
```

## Управление из Telegram

Запустите:

```bash
.venv/bin/tg-migrator watch
```

После этого отправляйте команды в собственное «Избранное»:

- `/transfer 100`
- `/transfer_from 01.06.2025`
- `/forward 100`
- `/forward_from 01.06.2025`
- `/status`
- `/cancel`
- `/help`

Перенос идёт от старых публикаций к новым. Один альбом считается одной
публикацией. Служебные сообщения о входе участников, закреплении и изменении
названия пропускаются.

## Автоматический запуск

Чтобы новые публикации переносились постоянно без ручного запуска:

```bash
.venv/bin/tg-migrator install-service
```

macOS будет запускать приложение при входе в систему и перезапускать его после
сбоя. Проверить состояние можно командой
`.venv/bin/tg-migrator service-status`, отключить — командой
`.venv/bin/tg-migrator uninstall-service`.

## Запуск в облаке (Hugging Face Spaces, бесплатно)

Вариант для работы 24/7 без своего сервера и без банковской карты.
Особенность бесплатных Spaces: диск не сохраняется между перезапусками,
поэтому сессия передаётся строкой `TG_SESSION_STRING`, а журнал уже
перенесённого после перезапуска начинается заново. Автоперенос новых
публикаций от этого не страдает, но массовые команды `/transfer …` после
перезапуска могут продублировать старые посты — сначала проверяйте
`/status` и переносите небольшими порциями.

1. Локально получите строку сессии (понадобится уже выполненный
   `tg-migrator auth`):

   ```bash
   .venv/bin/tg-migrator export-session
   ```

   Либо создайте отдельную сессию для сервера — Telegram пришлёт код
   подтверждения:

   ```bash
   .venv/bin/tg-migrator export-session --new
   ```

   Строка даёт полный доступ к аккаунту — никому её не передавайте.

2. Зарегистрируйтесь на [huggingface.co](https://huggingface.co) и создайте
   Space: **New Space → SDK: Docker → Blank**, оборудование —
   **CPU basic (бесплатно)**, видимость — **Private**.

3. В настройках Space (**Settings → Variables and secrets**) добавьте
   секреты: `TG_API_ID`, `TG_API_HASH`, `TG_PHONE`, `TG_SESSION_STRING`,
   `TG_SOURCE`, `TG_DESTINATION`.

4. Загрузите файлы проекта в Space — через веб-интерфейс
   (**Files → Upload files**) или через git:

   ```bash
   git remote add hf https://huggingface.co/spaces/<логин>/<имя-space>
   git push hf main
   ```

5. Space соберёт Docker-образ и запустит `tg-migrator watch`: в «Избранное»
   придёт сообщение «Переносчик запущен», а страница Space начнёт отвечать
   `tg-migrator: ok`.

6. Чтобы бесплатный Space не «уснул» от неактивности, настройте бесплатный
   пинг (UptimeRobot, cron-job.org) на адрес
   `https://<логин>-<имя-space>.hf.space` раз в 10–15 минут.

Не запускайте `watch` одновременно на Mac и в облаке с одной и той же
сессией: Telegram разрывает такие подключения. Перед переездом остановите
локальный автозапуск (`.venv/bin/tg-migrator uninstall-service`) или
используйте `export-session --new`.
