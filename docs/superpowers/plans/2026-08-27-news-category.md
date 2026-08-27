# News Category Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a separately managed news-source category and scheduled news slots that publish the newest unique Telegram news no older than three days.

**Architecture:** Source category is explicit and stored in `automation_sources`; queued posts snapshot it in `automation_queue`. Existing slot `kind` gains `news`; the controller uses a news-only freshness and selection path while preserving the existing media publisher. The Next.js panel manages the same fields in Neon and Render processes asynchronous source actions.

**Tech Stack:** Python 3.11, Telethon, SQLAlchemy, PostgreSQL/SQLite, Next.js 16, React 19, TypeScript, Zod, Vitest.

**Spec:** `docs/superpowers/specs/2026-08-27-news-category-design.md`

## Global Constraints

- Existing sources, queue rows and slots remain compatible and default to `content`.
- Valid categories are exactly `content` and `news`; valid slot kinds are exactly `any`, `video`, `image`, and `news`.
- News defaults to a 3-day freshness window configurable from 1 through 7 days.
- News selection is newest-first and bypasses minimum views/reactions.
- Existing deduplication, Telegram formatting/media handling, link cleaning and MAX signature behavior must not change.

---

### Task 1: Persist source and queue categories

**Files:**
- Modify: `tg_migrator/state.py`
- Test: `tests/test_state.py`

**Interfaces:**
- Produces: `Source.category: str`, `QueueItem.content_category: str`, `MigrationState.add_source(peer, title, category="content")`, `MigrationState.set_source_category(peer, category)`, category-aware queue filters.

- [ ] **Step 1: Write failing state tests**

Add tests that construct a legacy database, verify migration defaults to `content`, add a `news` source, enqueue a news item, change the source category, and verify only `pending`/`candidate` queue rows follow the change.

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `python3 -m pytest tests/test_state.py -q`

Expected: failures for missing `category`, `content_category`, and `set_source_category`.

- [ ] **Step 3: Implement schema migration and validated state methods**

Add migration definitions:

```python
"automation_sources": {
    "category": "TEXT NOT NULL DEFAULT 'content'",
    # existing fields remain
},
"automation_queue": {
    "content_category": "TEXT NOT NULL DEFAULT 'content'",
    # existing fields remain
},
```

Validate with a shared `CONTENT_CATEGORIES = {"content", "news"}`. Update `add_source`, `sources`, `enqueue`, `_queue_item`, `pending_items`, `pool_items`, and count/expiry helpers so `content_category` can be filtered independently from physical `media_kind`.

- [ ] **Step 4: Run state tests**

Run: `python3 -m pytest tests/test_state.py -q`

Expected: all state tests pass.

- [ ] **Step 5: Commit**

```bash
git add tg_migrator/state.py tests/test_state.py
git commit -m "feat: persist news source categories"
```

### Task 2: Collect and publish newest news

**Files:**
- Modify: `tg_migrator/automation.py`
- Modify: `tg_migrator/dashboard_actions.py`
- Test: `tests/test_automation.py`
- Test: `tests/test_dashboard_actions.py`

**Interfaces:**
- Consumes: category-aware state methods from Task 1.
- Produces: `AutomationController.add_source(raw, category="content")`, `publish_next("news")`, `/source_category`, `/news_fresh_days`, `/now news`, `/slot HH:MM news`.

- [ ] **Step 1: Write failing automation tests**

Cover these exact cases: ordinary refill excludes news sources; news refill excludes content sources; a news slot picks the newest eligible item even when an older item has a higher score; a news item older than three days expires; minimum views/reactions do not reject news; dashboard `add_source` passes category; dashboard `set_source_category` updates it.

- [ ] **Step 2: Run focused tests and verify failure**

Run: `python3 -m pytest tests/test_automation.py tests/test_dashboard_actions.py -q`

Expected: failures for unsupported `news` and missing category payload handling.

- [ ] **Step 3: Implement category-specific controller paths**

Use `news_fresh_days` default `3`. For `kind == "news"`, select only news sources, use the news cutoff, sort by `(published_at, score)` descending, and claim the first candidate. For `any|video|image`, select only content sources and keep the existing balanced activity selection. Refill both categories in `refill_loop`.

- [ ] **Step 4: Implement Telegram and dashboard action controls**

Accept `/add_source LINK news`, `/source_category SOURCE content|news`, `/news_fresh_days [1..7]`, `/now news`, and `/slot HH:MM news [SOURCE]`. Add dashboard action payloads `category` on `add_source` and `{source, category}` for `set_source_category`.

- [ ] **Step 5: Run focused tests**

Run: `python3 -m pytest tests/test_automation.py tests/test_dashboard_actions.py -q`

Expected: all focused tests pass.

- [ ] **Step 6: Commit**

```bash
git add tg_migrator/automation.py tg_migrator/dashboard_actions.py tests/test_automation.py tests/test_dashboard_actions.py
git commit -m "feat: schedule newest anime news"
```

### Task 3: Add news controls to the web panel

**Files:**
- Modify: `dashboard/src/lib/actions.ts`
- Modify: `dashboard/src/app/api/sources/route.ts`
- Modify: `dashboard/src/app/api/sources/actions/route.ts`
- Modify: `dashboard/src/app/sources/page.tsx`
- Modify: `dashboard/src/components/source-manager.tsx`
- Modify: `dashboard/src/app/api/schedule/route.ts`
- Modify: `dashboard/src/app/schedule/page.tsx`
- Modify: `dashboard/src/components/schedule-editor.tsx`
- Modify: `dashboard/src/app/api/settings/route.ts`
- Modify: `dashboard/src/components/settings-form.tsx`
- Modify: `dashboard/src/app/globals.css`
- Test: `dashboard/src/components/source-manager.test.tsx`
- Test: `dashboard/src/components/schedule-editor.test.tsx`
- Test: `dashboard/src/components/settings-form.test.tsx`
- Test: `dashboard/src/lib/actions.test.ts`

**Interfaces:**
- Consumes: `automation_sources.category`, `automation_slots.media_kind = 'news'`, and `automation_settings.news_fresh_days`.
- Produces: category selector and badge on Sources, `Новости` schedule option with compatible source filtering, and news freshness setting.

- [ ] **Step 1: Write failing panel tests**

Verify: add form submits `{operation:"add", source, category:"news"}`; an existing source can queue `set_category`; schedule schema accepts `news`; selecting `news` shows only news sources; settings schema accepts `newsFreshDays` from 1 through 7.

- [ ] **Step 2: Install dependencies and run focused tests to verify failure**

Run: `npm install && npm test -- --run src/components/source-manager.test.tsx src/components/schedule-editor.test.tsx src/components/settings-form.test.tsx src/lib/actions.test.ts`

Working directory: `dashboard`

Expected: tests fail because news fields and controls do not exist.

- [ ] **Step 3: Implement validated API and page data**

Extend Zod schemas with `category: z.enum(["content", "news"])`, schedule `mediaKind: "news"`, and `newsFreshDays`. Include source category in all source and schedule page queries and action payloads.

- [ ] **Step 4: Implement controls**

Add an `Обычный / Новости` selector to the add form, an editable selector and visible category badge to every source row, a `Новости` option to each schedule slot, filtering of the source selector by slot type, and the 1–7 day news freshness input.

- [ ] **Step 5: Run panel tests, typecheck and build**

Run in `dashboard`:

```bash
npm test -- --run
npm run typecheck
npm run build
```

Expected: all tests, typecheck, and production build pass.

- [ ] **Step 6: Commit**

```bash
git add dashboard
git commit -m "feat: manage news sources in dashboard"
```

### Task 4: Document, regress and publish

**Files:**
- Modify: `README.md`
- Verify: all Python and dashboard files changed above.

**Interfaces:**
- Produces: operator instructions for web and Telegram news controls.

- [ ] **Step 1: Update the README**

Document adding a news source from the website, `/add_source LINK news`, `/source_category`, `/news_fresh_days`, `/now news`, and a schedule slot with type `Новости`. State that existing sources stay ordinary after migration.

- [ ] **Step 2: Run full verification**

Run:

```bash
python3 -m pytest -q
python3 -m compileall -q tg_migrator tests
git diff --check
```

Run in `dashboard`:

```bash
npm test -- --run
npm run typecheck
npm run build
```

Expected: every command exits 0.

- [ ] **Step 3: Commit documentation**

```bash
git add README.md
git commit -m "docs: explain news scheduling"
```

- [ ] **Step 4: Push the branch**

```bash
git push -u origin codex/news-category
```

Expected: GitHub accepts the branch; Render/Vercel remain unchanged until merge.
