# Desiree Control Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a password-protected Vercel dashboard that shows Desiree's visual queue and controls its Neon-backed Telegram/MAX automation without opening another Telegram session.

**Architecture:** The existing Python worker remains the only Telegram/MAX actor on Render. A Next.js application in `dashboard/` reads Neon directly for authenticated views and writes either validated settings or durable action requests; the worker atomically claims those requests, executes them through the current controller/publisher, and stores results.

**Tech Stack:** Python 3.12, Telethon, SQLAlchemy, PostgreSQL/Neon, Pillow, Next.js App Router, React, TypeScript, `pg`, Zod, bcryptjs, jose, Vitest, Testing Library, Playwright, Vercel, Render.

**Spec:** `docs/superpowers/specs/2026-08-25-desiree-control-panel-design.md`

## Global Constraints

- Keep the Render worker attached to the repository-root `Dockerfile`; Vercel uses only `dashboard/`.
- Keep Telegram and MAX credentials on Render; the browser and dashboard responses never receive them.
- Store only bounded JPEG/WebP previews in Neon, never full media.
- Display sorting never changes automatic smart selection.
- `min_reactions=0` and `min_views=0` disable their automatic thresholds.
- Manual `Publish now` bypasses engagement thresholds but never duplicate protection.
- Telegram commands remain operational as a fallback.
- Display and edit schedule times in the worker's existing `Europe/Moscow` timezone.
- Ordinary Render sleep leaves dashboard actions in `pending`; no UI success appears before worker completion.
- Preserve the unrelated local modification in `telegram_post_migrator.egg-info/SOURCES.txt` and never stage it.

---

### Task 1: Extend the persistent queue and add dashboard actions

**Files:**
- Modify: `tg_migrator/state.py`
- Modify: `tests/test_state.py`

**Interfaces:**
- Produces: `QueueItem.caption_excerpt`, `views_count`, `reactions_count`, `forwards_count`, `preview_mime`, and `preview_data`.
- Produces: `Source.availability`, `checked_at`, and `error`, plus `update_source_availability`.
- Produces: `DashboardAction` and state methods `enqueue_action`, `claim_action`, `complete_action`, `fail_action`, `recent_actions`, `skip_item`, `update_post_metadata`, and `touch_worker_heartbeat`.
- Consumes: existing `MigrationState`, `QueueItem`, queue statuses, and SQLAlchemy engine.

- [ ] **Step 1: Write failing additive-schema and metric persistence tests**

Add tests that create old queue/source schemas manually, open `MigrationState`,
enqueue a post, store metrics/preview and source availability, close and reopen
it, then assert:

```python
saved = state.queue_item(item.id)
self.assertEqual(saved.caption_excerpt, "caption")
self.assertEqual(saved.views_count, 5000)
self.assertEqual(saved.reactions_count, 120)
self.assertEqual(saved.forwards_count, 31)
self.assertEqual(saved.preview_mime, "image/webp")
self.assertEqual(saved.preview_data, b"preview")
self.assertEqual(state.sources()[0].availability, "available")
```

- [ ] **Step 2: Write failing action atomicity tests**

Cover one active publish action per queue item, one successful atomic claimant,
completion, safe failure text truncation, and skip only from `pending`:

```python
action = state.enqueue_action("publish_now", {"item_id": item.id}, item.id)
self.assertIsNotNone(action)
self.assertIsNone(state.enqueue_action("publish_now", {"item_id": item.id}, item.id))
self.assertEqual(state.claim_action().id, action.id)
self.assertIsNone(state.claim_action())
state.complete_action(action.id, {"max_mid": "mid-1"})
self.assertEqual(state.action(action.id).status, "completed")
```

- [ ] **Step 3: Run state tests and verify the new tests fail**

Run: `python3 -m pytest tests/test_state.py -q`

Expected: failures for missing queue fields and action methods.

- [ ] **Step 4: Implement idempotent schema evolution**

Use SQLAlchemy inspection before `ALTER TABLE`, selecting `BLOB` for SQLite and
`BYTEA` for PostgreSQL. Add defaults so existing rows remain readable:

```python
@dataclass(frozen=True)
class DashboardAction:
    id: str
    kind: str
    payload: dict[str, object]
    status: str
    queue_item_id: str | None
    result: dict[str, object] | None
    error: str | None
    created_at: datetime
    claimed_at: datetime | None
    completed_at: datetime | None
```

Add nullable/defaulted availability fields to `automation_sources`. Create
`automation_actions` plus a partial unique index for active
`publish_now` actions. Keep payload/result as JSON text for SQLite/PostgreSQL
compatibility.

- [ ] **Step 5: Implement state methods with guarded updates**

Use `UPDATE automation_queue SET status = :next_status WHERE id = :id AND status = :current_status`
guards for claims, completion, failure,
skip, and retry. Make `claim_action()` select oldest pending action and change
it to `processing` in one transaction. Limit preview data to 131072 bytes in
`update_post_metadata`; reject larger values with `ValueError`.

- [ ] **Step 6: Run the focused and full Python suites**

Run: `python3 -m pytest tests/test_state.py -q`

Expected: all state tests pass.

Run: `python3 -m pytest -q`

Expected: the full existing suite passes.

- [ ] **Step 7: Commit Task 1**

```bash
git add tg_migrator/state.py tests/test_state.py
git commit -m "feat: persist dashboard queue data and actions"
```

---

### Task 2: Persist live engagement metrics and enforce automatic thresholds

**Files:**
- Create: `tg_migrator/post_metadata.py`
- Modify: `tg_migrator/selection.py`
- Modify: `tg_migrator/automation.py`
- Modify: `tests/test_selection.py`
- Modify: `tests/test_automation.py`

**Interfaces:**
- Produces: `PostMetrics`, `post_metrics(post)`, and `caption_excerpt(post, limit=500)`.
- Produces: automatic `min_reactions` and `min_views` filtering inside `_claim_smart`.
- Consumes: Task 1 `QueueItem` metric fields and `MigrationState.update_post_metadata`.

- [ ] **Step 1: Write failing metric extraction tests**

Cover albums, missing counters, multiple reaction types, and caption truncation:

```python
metrics = post_metrics(post_from_messages((first, second)))
assert metrics.views == 3000
assert metrics.reactions == 75
assert metrics.forwards == 20
assert caption_excerpt(post).endswith("…")
```

- [ ] **Step 2: Write failing threshold selection tests**

Queue three posts and set `min_reactions=100`, `min_views=5000`. Assert the
automatic selector ignores posts below either threshold, `0` disables each
threshold, and an exact manual claim can still select a below-threshold item.

- [ ] **Step 3: Run focused tests and verify failure**

Run: `python3 -m pytest tests/test_selection.py tests/test_automation.py -q`

Expected: failures for missing metric extraction and threshold behavior.

- [ ] **Step 4: Implement the metadata module**

```python
@dataclass(frozen=True)
class PostMetrics:
    views: int
    reactions: int
    forwards: int

def post_metrics(post: Post) -> PostMetrics:
    views = sum(int(getattr(message, "views", 0) or 0) for message in post.messages)
    forwards = sum(int(getattr(message, "forwards", 0) or 0) for message in post.messages)
    reactions = sum(
        int(getattr(result, "count", 0) or 0)
        for message in post.messages
        for result in (getattr(getattr(message, "reactions", None), "results", None) or ())
    )
    return PostMetrics(views=views, reactions=reactions, forwards=forwards)
```

Refactor `post_smart_score` to consume `post_metrics` so dashboard counters and
ranking use the same source values.

- [ ] **Step 5: Save metrics during enqueue and live refresh**

After `state.enqueue`, call `update_post_metadata` with the caption and counters.
When `_refresh_pending_scores` fetches live messages, update both the score and
separate counters in the same state method.

- [ ] **Step 6: Filter only automatic candidates**

Read settings using safe non-negative parsing:

```python
minimum_reactions = max(0, int(state.get_setting("min_reactions", "0") or 0))
minimum_views = max(0, int(state.get_setting("min_views", "0") or 0))
candidates = [
    item for item in candidates
    if item.reactions_count >= minimum_reactions
    and item.views_count >= minimum_views
]
```

Keep `claim_item(item_id)` unchanged for manual publication.

- [ ] **Step 7: Run focused and full suites**

Run: `python3 -m pytest tests/test_selection.py tests/test_automation.py -q`

Expected: focused tests pass.

Run: `python3 -m pytest -q`

Expected: full suite passes.

- [ ] **Step 8: Commit Task 2**

```bash
git add tg_migrator/post_metadata.py tg_migrator/selection.py tg_migrator/automation.py tests/test_selection.py tests/test_automation.py
git commit -m "feat: store engagement metrics and thresholds"
```

---

### Task 3: Capture bounded image and video previews

**Files:**
- Create: `tg_migrator/previews.py`
- Modify: `tg_migrator/automation.py`
- Modify: `pyproject.toml`
- Create: `tests/test_previews.py`
- Modify: `tests/test_automation.py`

**Interfaces:**
- Produces: `Preview(mime_type: str, data: bytes)` and `capture_preview(client, messages, max_bytes=131072)`.
- Consumes: Task 1 `MigrationState.update_post_metadata` preview fields.

- [ ] **Step 1: Write failing preview tests**

Use Pillow to generate an oversized in-memory image. Test photo resize, video
thumbnail selection, output dimensions at most 720 pixels, maximum 131072 bytes,
and `None` for absent or invalid media.

- [ ] **Step 2: Run the preview test and verify failure**

Run: `python3 -m pytest tests/test_previews.py -q`

Expected: import failure because `tg_migrator.previews` does not exist.

- [ ] **Step 3: Add Pillow and implement bounded conversion**

Add `Pillow==11.3.0` to Python dependencies. Download Telegram's small photo or
largest document/video thumbnail as bytes, open it with Pillow, normalize to
RGB, resize with `thumbnail((720, 720))`, and encode WebP while reducing quality
from 76 to 48 until within the byte limit:

```python
@dataclass(frozen=True)
class Preview:
    mime_type: str
    data: bytes
```

Return `None` on unsupported media or image decoding failure.

- [ ] **Step 4: Capture previews only when missing**

During enqueue/refill, call `capture_preview` for a newly added item. During
metric refresh, do not redownload an existing preview. Preview failure must not
fail the queue item.

- [ ] **Step 5: Run preview, automation, and full tests**

Run: `python3 -m pytest tests/test_previews.py tests/test_automation.py -q`

Expected: focused tests pass.

Run: `python3 -m pytest -q && python3 -m compileall -q tg_migrator tests`

Expected: exit code 0.

- [ ] **Step 6: Commit Task 3**

```bash
git add pyproject.toml tg_migrator/previews.py tg_migrator/automation.py tests/test_previews.py tests/test_automation.py
git commit -m "feat: capture bounded queue previews"
```

---

### Task 4: Execute dashboard actions and report worker heartbeat

**Files:**
- Create: `tg_migrator/dashboard_actions.py`
- Modify: `tg_migrator/automation.py`
- Modify: `tg_migrator/watch.py`
- Create: `tests/test_dashboard_actions.py`
- Modify: `tests/test_watch.py`

**Interfaces:**
- Produces: `DashboardActionRunner.run_once()` and `DashboardActionRunner.loop()`.
- Produces: `AutomationController.publish_item(item_id)` for exact manual publication.
- Consumes: Task 1 action state methods and existing source/parse/publisher methods.

- [ ] **Step 1: Write failing action execution tests**

Cover these action kinds with fakes: `publish_now`, `add_source`, `remove_source`,
`scan`, `retry`, and `max_probe`. Assert payload validation, exact item use,
completion result, source availability success/failure, safe failure, and no
duplicate execution after restart.

- [ ] **Step 2: Write failing heartbeat test**

Start the automation watcher with a fake state clock and assert the worker writes
an ISO UTC heartbeat before waiting for Telegram updates and continues updating
it independently of publications.

- [ ] **Step 3: Run focused tests and verify failure**

Run: `python3 -m pytest tests/test_dashboard_actions.py tests/test_watch.py -q`

Expected: failures for missing runner and heartbeat task.

- [ ] **Step 4: Implement exact manual publication**

```python
async def publish_item(self, item_id: str) -> QueueItem:
    item = self.state.claim_item(item_id)
    if item is None:
        raise ValueError("Пост уже обработан или недоступен.")
    try:
        await self.publisher.publish(item)
    except Exception:
        self.state.release(item.id)
        raise
    self.state.set_setting("last_published_source", item.source)
    return item
```

Use existing ambiguous-publication handling from `PostPublisher`; do not retry
an uncertain MAX send automatically.

- [ ] **Step 5: Implement the action runner**

Validate each JSON payload before dispatch. `run_once()` claims one action,
executes it, records a compact JSON result, and catches exceptions into a safe
error string. `loop()` processes available actions and waits five seconds when
empty.

- [ ] **Step 6: Add worker tasks**

Start named tasks `dashboard-actions` and `worker-heartbeat` beside refill and
scheduler tasks in `_run_automation_watcher`. Cancel and gather all tasks in the
existing `finally` block.

- [ ] **Step 7: Run focused and full suites**

Run: `python3 -m pytest tests/test_dashboard_actions.py tests/test_watch.py -q`

Expected: focused tests pass.

Run: `python3 -m pytest -q`

Expected: full suite passes.

- [ ] **Step 8: Commit Task 4**

```bash
git add tg_migrator/dashboard_actions.py tg_migrator/automation.py tg_migrator/watch.py tests/test_dashboard_actions.py tests/test_watch.py
git commit -m "feat: execute dashboard actions on worker"
```

---

### Task 5: Scaffold the Vercel application and secure login

**Files:**
- Create: `dashboard/package.json`
- Create: `dashboard/package-lock.json`
- Create: `dashboard/next.config.ts`
- Create: `dashboard/tsconfig.json`
- Create: `dashboard/eslint.config.mjs`
- Create: `dashboard/vitest.config.ts`
- Create: `dashboard/src/app/layout.tsx`
- Create: `dashboard/src/app/login/page.tsx`
- Create: `dashboard/src/app/api/session/login/route.ts`
- Create: `dashboard/src/app/api/session/logout/route.ts`
- Create: `dashboard/src/lib/auth.ts`
- Create: `dashboard/src/lib/env.ts`
- Create: `dashboard/src/lib/db.ts`
- Create: `dashboard/scripts/hash-password.mjs`
- Create: `dashboard/src/lib/auth.test.ts`
- Create: `dashboard/src/app/api/session/login/route.test.ts`

**Interfaces:**
- Produces: `requireSession()`, `createSessionCookie()`, `clearSessionCookie()`, `verifyPassword()`, and `requireSameOrigin(request)`.
- Produces: `query<T>(text: string, values?: unknown[]): Promise<T[]>` backed by Neon `DATABASE_URL`.
- Consumes: Vercel server environment only.

- [ ] **Step 1: Create the package manifest and testing configuration**

Use Next.js App Router with scripts `dev`, `build`, `lint`, `typecheck`, `test`,
and `test:e2e`. Add runtime dependencies `next`, `react`, `react-dom`, `pg`,
`zod`, `bcryptjs`, and `jose`; add TypeScript, Vitest, jsdom, Testing Library,
ESLint, and Playwright development dependencies.

- [ ] **Step 2: Write failing authentication tests**

Test correct/incorrect bcrypt password verification, missing environment values,
signed cookie verification, expired cookies, unauthenticated redirects, login
rate-limit response, and same-origin rejection for a foreign `Origin`.

- [ ] **Step 3: Run tests and verify failure**

Run: `cd dashboard && npm test -- --run`

Expected: failures because authentication modules/routes do not exist.

- [ ] **Step 4: Implement strict environment and database modules**

Parse only server variables:

```ts
const Env = z.object({
  DATABASE_URL: z.string().url(),
  ADMIN_PASSWORD_HASH: z.string().min(40),
  AUTH_SECRET: z.string().min(32),
});
```

Create a cached `pg.Pool` with `max: 2`, SSL required, and parameterized queries.

- [ ] **Step 5: Implement login and signed cookie auth**

Use bcryptjs for the password hash and jose `SignJWT`/`jwtVerify` for a seven-day
`desiree_session` cookie with `httpOnly`, `secure`, `sameSite: "lax"`, and
`path: "/"`. Add a small database-backed or in-memory per-instance login delay
after five failures without revealing whether environment configuration exists.

- [ ] **Step 6: Implement login UI and password hash script**

The script accepts the password from a hidden terminal prompt or stdin and prints
only the bcrypt hash. The login page shows a single password field, submit state,
and generic Russian error text.

- [ ] **Step 7: Run dashboard checks**

Run: `cd dashboard && npm test -- --run && npm run typecheck && npm run lint && npm run build`

Expected: all commands exit 0.

- [ ] **Step 8: Commit Task 5**

```bash
git add dashboard
git commit -m "feat: scaffold secure Desiree dashboard"
```

---

### Task 6: Add authenticated dashboard read APIs

**Files:**
- Create: `dashboard/src/lib/queue-query.ts`
- Create: `dashboard/src/lib/types.ts`
- Create: `dashboard/src/app/api/overview/route.ts`
- Create: `dashboard/src/app/api/queue/route.ts`
- Create: `dashboard/src/app/api/queue/[id]/preview/route.ts`
- Create: `dashboard/src/app/api/activity/route.ts`
- Create: `dashboard/src/app/api/actions/[id]/route.ts`
- Create: `dashboard/src/app/api/sources/route.ts`
- Create: `dashboard/src/app/api/schedule/route.ts`
- Create: `dashboard/src/app/api/settings/route.ts`
- Create: `dashboard/src/lib/queue-query.test.ts`
- Create: `dashboard/src/app/api/queue/route.test.ts`

**Interfaces:**
- Produces: `QueueSort = "newest" | "reactions" | "views" | "score"` and validated `QueueFilters`.
- Produces: authenticated JSON endpoints and private preview bytes.
- Consumes: Task 5 auth/query helpers and Task 1 database schema.

- [ ] **Step 1: Write failing queue query tests**

Assert that every sort maps to a fixed SQL fragment, filters stay parameterized,
page size is clamped to 10–60, invalid values return 400, and SQL injection text
never enters the `ORDER BY` clause.

- [ ] **Step 2: Write failing route authorization and response tests**

Test unauthenticated 401, sanitized queue rows, pagination cursor, explicit zero
metrics for legacy rows, 404 preview fallback, and `Cache-Control: private`.

- [ ] **Step 3: Run focused tests and verify failure**

Run: `cd dashboard && npm test -- --run src/lib/queue-query.test.ts src/app/api/queue/route.test.ts`

Expected: failures for missing modules/routes.

- [ ] **Step 4: Implement validated queue SQL**

Use a constant sort map:

```ts
const SORT_SQL: Record<QueueSort, string> = {
  newest: "published_at DESC, id DESC",
  reactions: "reactions_count DESC, published_at DESC",
  views: "views_count DESC, published_at DESC",
  score: "score DESC, published_at DESC",
};
```

Parameterize source, media type, status, minimum metrics, cursor, and limit.

- [ ] **Step 5: Implement overview, queue, and preview routes**

Calculate heartbeat status from `worker_heartbeat_at`: active at at most 120
seconds, delayed at at most 300 seconds, otherwise offline. Never expose
`preview_data` in queue JSON; serve it only from the authenticated preview route.

- [ ] **Step 6: Implement activity, source, schedule, and settings reads**

Return only safe action summaries and whitelisted setting keys:
`fresh_days`, `min_reactions`, `min_views`, `signature_text`, and
`signature_url`. The single-action route returns one authenticated action for
the queue card's completion polling.

- [ ] **Step 7: Run dashboard checks**

Run: `cd dashboard && npm test -- --run && npm run typecheck && npm run lint && npm run build`

Expected: all commands exit 0.

- [ ] **Step 8: Commit Task 6**

```bash
git add dashboard/src
git commit -m "feat: expose authenticated dashboard reads"
```

---

### Task 7: Add validated control APIs

**Files:**
- Create: `dashboard/src/lib/actions.ts`
- Create: `dashboard/src/app/api/queue/[id]/publish/route.ts`
- Create: `dashboard/src/app/api/queue/[id]/skip/route.ts`
- Create: `dashboard/src/app/api/queue/[id]/retry/route.ts`
- Create: `dashboard/src/app/api/sources/actions/route.ts`
- Create: `dashboard/src/app/api/scans/route.ts`
- Create: `dashboard/src/app/api/actions/max-probe/route.ts`
- Create: `dashboard/src/app/api/schedule/[time]/route.ts`
- Modify: `dashboard/src/app/api/schedule/route.ts`
- Modify: `dashboard/src/app/api/settings/route.ts`
- Create: `dashboard/src/lib/actions.test.ts`
- Create: `dashboard/src/app/api/settings/route.test.ts`

**Interfaces:**
- Produces: `createAction(kind, payload, queueItemId?)` with active publish uniqueness handling.
- Produces: authenticated state-changing routes with same-origin validation.
- Consumes: Task 1 action schema and Task 5 auth/query helpers.

- [ ] **Step 1: Write failing mutation tests**

Cover duplicate publish returning the existing active action, skip only pending,
retry only failed/ambiguous, source link validation, scan count/date validation,
`HH:MM` schedule validation, allowed media types, URL signature validation,
freshness 1–90, and non-negative integer thresholds.

- [ ] **Step 2: Run mutation tests and verify failure**

Run: `cd dashboard && npm test -- --run src/lib/actions.test.ts src/app/api/settings/route.test.ts`

Expected: failures for missing action and mutation modules.

- [ ] **Step 3: Implement durable action creation**

Insert JSON payload with parameterized SQL and handle the active-publish unique
constraint by reading and returning the existing action instead of creating a
second request.

- [ ] **Step 4: Implement queue action routes**

`publish` creates `publish_now`; `skip` performs a guarded direct queue update;
`retry` performs the existing allowed state transition. Every response returns
the resulting item/action state, not an optimistic published result.

- [ ] **Step 5: Implement source and scan action routes**

Map source operations to `add_source` and `remove_source`; map scan input to the
worker `scan` payload with `source`, `count`, optional `start`, optional `end`,
and `media_kind`. The MAX probe route creates a `max_probe` action without
touching the publication queue.

- [ ] **Step 6: Implement schedule and setting writes**

Use database transactions and upserts. Whitelist setting keys and validate all
values before SQL. `min_reactions` and `min_views` accept integers 0–1,000,000;
signature URL accepts only HTTP/HTTPS.

- [ ] **Step 7: Run dashboard checks**

Run: `cd dashboard && npm test -- --run && npm run typecheck && npm run lint && npm run build`

Expected: all commands exit 0.

- [ ] **Step 8: Commit Task 7**

```bash
git add dashboard/src
git commit -m "feat: add dashboard control APIs"
```

---

### Task 8: Build the visual queue and overview interface

**Files:**
- Create: `dashboard/src/app/page.tsx`
- Create: `dashboard/src/app/queue/page.tsx`
- Create: `dashboard/src/components/app-shell.tsx`
- Create: `dashboard/src/components/status-cards.tsx`
- Create: `dashboard/src/components/queue-controls.tsx`
- Create: `dashboard/src/components/queue-card.tsx`
- Create: `dashboard/src/components/action-button.tsx`
- Create: `dashboard/src/lib/client-api.ts`
- Create: `dashboard/src/app/globals.css`
- Create: `dashboard/src/components/queue-card.test.tsx`
- Create: `dashboard/src/app/queue/page.test.tsx`

**Interfaces:**
- Produces: responsive Russian overview and visual queue pages.
- Consumes: Tasks 6–7 read/control APIs.

- [ ] **Step 1: Write failing component tests**

Assert queue cards render preview or placeholder, caption, metrics, source, date,
media/status badges, and available actions. Assert sort/filter controls update
the request but not automatic settings. Assert publish disables on first click
and shows `Ожидает бота` until action completion.

- [ ] **Step 2: Run component tests and verify failure**

Run: `cd dashboard && npm test -- --run src/components/queue-card.test.tsx src/app/queue/page.test.tsx`

Expected: failures for missing components/pages.

- [ ] **Step 3: Implement shared shell and overview**

Create navigation for `Главная`, `Очередь`, `Источники`, `Расписание`,
`Настройки`, and `События`. Show worker state with text and color, queue counts,
thresholds, freshness, and latest safe event.

- [ ] **Step 4: Implement queue filters and cards**

Use URL search parameters for sort/filter state so refresh preserves the view.
Lazy-load preview URLs. Use a media placeholder when preview fails. Add
pagination without loading binary data in JSON.

- [ ] **Step 5: Implement action polling**

After publish, poll the single action every three seconds; stop at completed or
failed. Refresh the queue after skip/retry/publication completion. Avoid full
page reloads and show server error text safely.

- [ ] **Step 6: Add responsive styling**

Use a compact single-column mobile layout and a 2–4 column desktop card grid.
Keep touch targets at least 44 pixels, visible focus outlines, readable metric
labels, and no horizontal overflow at 375 pixels.

- [ ] **Step 7: Run component and production checks**

Run: `cd dashboard && npm test -- --run && npm run typecheck && npm run lint && npm run build`

Expected: all commands exit 0.

- [ ] **Step 8: Commit Task 8**

```bash
git add dashboard/src
git commit -m "feat: build visual queue dashboard"
```

---

### Task 9: Build sources, schedule, settings, and activity pages

**Files:**
- Create: `dashboard/src/app/sources/page.tsx`
- Create: `dashboard/src/app/schedule/page.tsx`
- Create: `dashboard/src/app/settings/page.tsx`
- Create: `dashboard/src/app/activity/page.tsx`
- Create: `dashboard/src/components/source-manager.tsx`
- Create: `dashboard/src/components/scan-form.tsx`
- Create: `dashboard/src/components/schedule-editor.tsx`
- Create: `dashboard/src/components/settings-form.tsx`
- Create: `dashboard/src/components/activity-list.tsx`
- Create: `dashboard/src/components/settings-form.test.tsx`
- Create: `dashboard/src/components/schedule-editor.test.tsx`

**Interfaces:**
- Produces: all remaining first-version control pages.
- Consumes: Tasks 6–7 API contracts and shared Task 8 shell/client helper.

- [ ] **Step 1: Write failing form tests**

Test source add/remove confirmation state, scan inputs, time/media/source schedule
editing, `0` threshold labels as disabled, signature validation, freshness
validation, MAX probe pending/result states, pending action display, and safe
activity errors.

- [ ] **Step 2: Run component tests and verify failure**

Run: `cd dashboard && npm test -- --run src/components/settings-form.test.tsx src/components/schedule-editor.test.tsx`

Expected: failures for missing components.

- [ ] **Step 3: Implement source and scan controls**

Show current source status and action progress. Disable duplicate submissions.
Removing a source states that queued/history rows remain.

- [ ] **Step 4: Implement schedule editor**

Edit slots inline with `HH:MM`, any/video/image, and optional existing source.
Sort slots by time and show server validation errors beside the row.

- [ ] **Step 5: Implement settings and activity pages**

Separate automatic thresholds from queue display sorting. Explain `0` as
`без ограничения`. Save MAX signature label/URL and freshness. Add a
`Проверить MAX` button that queues `max_probe` and shows its result. Activity shows
action type, status, target, timestamps, and safe result/error.

- [ ] **Step 6: Run dashboard checks**

Run: `cd dashboard && npm test -- --run && npm run typecheck && npm run lint && npm run build`

Expected: all commands exit 0.

- [ ] **Step 7: Commit Task 9**

```bash
git add dashboard/src
git commit -m "feat: add dashboard management pages"
```

---

### Task 10: End-to-end verification, documentation, and deployment handoff

**Files:**
- Create: `dashboard/playwright.config.ts`
- Create: `dashboard/e2e/control-panel.spec.ts`
- Create: `dashboard/.env.example`
- Modify: `.gitignore`
- Modify: `README.md`
- Modify: `render.yaml`
- Create: `docs/dashboard-deployment.md`

**Interfaces:**
- Produces: reproducible local/production deployment instructions and browser smoke coverage.
- Consumes: all previous tasks.

- [ ] **Step 1: Add an authenticated browser smoke test**

Seed a test database, start Next locally, log in, assert overview state, sort the
queue by reactions and views, filter video, open an image preview, change a
threshold, create a harmless pending scan in test data, and verify mobile width
375 plus desktop width 1440 without overflow.

- [ ] **Step 2: Run the smoke test and fix only observed failures**

Run: `cd dashboard && npx playwright install chromium && npm run test:e2e`

Expected: all Playwright tests pass with no console errors.

- [ ] **Step 3: Document local and hosted setup**

Document:

```text
Vercel Root Directory: dashboard
Vercel variables: DATABASE_URL, ADMIN_PASSWORD_HASH, AUTH_SECRET
Render root: repository root Dockerfile
```

Include exact password-hash command, random `AUTH_SECRET` command, Neon pooled
URL requirement, Vercel import steps, Render-first deployment order, and safe
rollback steps. `.env.example` contains names and non-secret examples only.

- [ ] **Step 4: Run all fresh verification gates**

Run:

```bash
python3 -m pytest -q
python3 -m compileall -q tg_migrator tests
git diff --check
cd dashboard
npm test -- --run
npm run typecheck
npm run lint
npm run build
npm run test:e2e
```

Expected: every command exits 0.

- [ ] **Step 5: Commit Task 10**

```bash
git add .gitignore README.md render.yaml dashboard docs/dashboard-deployment.md
git commit -m "docs: add dashboard deployment and smoke coverage"
```

- [ ] **Step 6: Review and publish the branch**

Inspect `git status`, `git diff origin/main..HEAD --stat`, and recent commits.
Confirm `telegram_post_migrator.egg-info/SOURCES.txt` is not staged. Push the
intended commits to `main` only after all gates pass.

- [ ] **Step 7: Verify deployments without publishing content**

Confirm Render reports the pushed commit and returns `HTTP 200`. Confirm the
worker heartbeat becomes active and dashboard action polling runs. Configure
Vercel environment variables, deploy `dashboard/`, log in, inspect queue
previews and sorting, and save/read a harmless setting. Do not click production
`Publish now` until the owner explicitly approves that final live post.
