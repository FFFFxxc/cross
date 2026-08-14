# Prepare Render Env Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one secure local command that authorizes a separate Telegram account and copies a complete Render env block without persisting or printing secrets.

**Architecture:** Keep env rendering and clipboard transfer in a focused `render_env` module. The CLI collects secrets with `getpass`, creates a fresh in-memory Telethon `StringSession`, then copies the rendered values using macOS `pbcopy`.

**Tech Stack:** Python 3.11+, Telethon, stdlib `getpass`, `json`, and `subprocess`.

## Global Constraints

- Do not modify the existing Desiree file session or Keychain phone.
- Do not print or write any secret to disk.
- Always render `TG_AUTOMATION_ENABLED=false` for first deploy.
- Use owner `8235497168`, Telegram target `webnmy`, initial source `animeworldmem`, and MAX channel `channel_animenaruto`.

---

### Task 1: Secure Render environment wizard

**Files:**
- Create: `tg_migrator/render_env.py`
- Create: `tests/test_render_env.py`
- Modify: `tg_migrator/__main__.py`
- Modify: `README.md`

**Interfaces:**
- Produces: `build_render_env(values: RenderEnvValues) -> str`
- Produces: `copy_to_clipboard(block: str) -> None`
- Produces: CLI command `tg-migrator prepare-render`

- [ ] **Step 1: Write failing renderer and validation tests**

Create literal expectations for all Render keys, quoted special values, the disabled automation flag, rejected empty secrets, and clipboard failure converted to `ConfigError`.

- [ ] **Step 2: Verify RED**

Run: `python3 -m pytest -q tests/test_render_env.py`
Expected: FAIL because `tg_migrator.render_env` does not exist.

- [ ] **Step 3: Implement the focused module**

Add an immutable `RenderEnvValues` dataclass, dotenv-safe JSON quoting, required-value validation, and `pbcopy` transfer with no return value or secret output.

- [ ] **Step 4: Verify GREEN**

Run: `python3 -m pytest -q tests/test_render_env.py`
Expected: PASS.

- [ ] **Step 5: Add the CLI flow**

Register `prepare-render`; load the existing API ID/hash, ask the new phone, Neon URL, and MAX token with `getpass`, authorize a fresh StringSession, copy the block, disconnect, and print only the authorized account name/ID plus safe next steps.

- [ ] **Step 6: Document the one-command workflow**

Add `tg-migrator prepare-render`, Neon password rotation, Render bulk import, and the safe `false` to `true` cutover to `README.md`.

- [ ] **Step 7: Verify and commit**

Run: `git diff --check && python3 -m compileall -q tg_migrator tests && python3 -m pytest -q`
Expected: all tests pass and no secrets appear in the diff.

Commit: `feat: add secure Render env wizard`.
