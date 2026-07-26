# Удаление MAX-промо Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Копировать посты в открытый канал без MAX-ссылки и фразы «мы в Максе», сохраняя медиа, Telegram-ссылку и форматирование.

**Architecture:** Добавить чистую функцию очистки текста и Telegram entities в `selection.py`; после обычного `forward_messages` редактировать созданные копии в `migrator.py`. Отбор постов остаётся прежним и продолжает разрешать MAX-ссылку.

**Tech Stack:** Python 3.12, Telethon, unittest, Docker/Render.

## Global Constraints

- Удалять точную MAX-ссылку `https://max.ru/channel_anime2d`.
- Удалять варианты «мы в Максе» без учёта регистра, пробелов и окружающей пунктуации.
- Сохранять `https://t.me/fulli4k_bot`, медиа и оставшееся форматирование.
- Не менять команды, дедупликацию и автоматический перенос.

### Task 1: Text and entity sanitizer

**Files:**
- Modify: `tg_migrator/selection.py`
- Test: `tests/test_selection.py`

- [ ] Write failing tests for removing MAX URL, case-insensitive phrase, preserving Telegram URL, and shifting/removing overlapping entities.
- [ ] Run the focused tests and confirm they fail because sanitizer is absent.
- [ ] Implement `sanitize_message_text(text, entities)` returning cleaned text and adjusted entities, using UTF-16 offsets required by Telegram.
- [ ] Run focused tests and then the full test suite.

### Task 2: Apply sanitizer after copy

**Files:**
- Modify: `tg_migrator/migrator.py`
- Test: `tests/test_migrator.py`

- [ ] Write a failing integration-style test with a fake client proving forwarded copies are edited with cleaned text and entities before state is marked.
- [ ] Run the test and confirm failure.
- [ ] Implement post-copy editing for every returned Telegram message with text/caption, leaving media and album behavior intact.
- [ ] Ensure an edit failure prevents `mark_transferred`.
- [ ] Run migrator tests and the full suite.

### Task 3: Verify, publish, and deploy

**Files:**
- Modify: `README.md` only if command behavior needs documentation.

- [ ] Run all tests, type/compile checks, and Docker build.
- [ ] Review diff and confirm unrelated `telegram_post_migrator.egg-info/SOURCES.txt` remains untouched.
- [ ] Commit and push the implementation to `main`.
- [ ] Manually deploy the pushed commit on Render, wait for `Live`, and inspect deploy logs for a successful startup.
- [ ] Tell the user to run `/transfer 3` for already missed posts; future posts will be cleaned automatically.
