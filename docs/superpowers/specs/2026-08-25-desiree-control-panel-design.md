# Desiree Control Panel Design

## Goal

Add a password-protected web panel for the existing Desiree Telegram/MAX
automation. The panel replaces most routine Telegram commands with buttons,
while the current commands remain available as a fallback.

The first version must let the owner inspect the queue visually, sort it by
reactions or views, publish a selected post manually, manage sources and the
schedule, and set minimum engagement thresholds for automatic publication.

## Architecture

- Keep the Python/Telethon worker on Render.
- Add a Next.js application under `dashboard/` and deploy that directory to
  Vercel.
- Use the existing Neon PostgreSQL database as the shared control plane.
- Vercel reads dashboard data and writes settings or action requests to Neon.
- Only the Render worker performs Telegram and MAX operations.
- Do not open a second Telegram session from Vercel.

The existing root Docker build remains unchanged, so adding the dashboard does
not alter how Render starts the worker.

## Authentication and security

- The panel has one administrator account and no public registration.
- Vercel stores `ADMIN_PASSWORD_HASH`, `AUTH_SECRET`, and `DATABASE_URL` as
  server-only environment variables.
- Password verification runs only on the server.
- A successful login creates a signed, HTTP-only, secure, same-site cookie.
- State-changing API routes verify the session, request origin, input shape,
  and the current database state.
- Telegram session data, Telegram API credentials, and MAX credentials remain
  only on Render and are never returned by the dashboard API.
- Preview responses require the authenticated cookie and use private caching.

## Dashboard pages

### Overview

Show:

- worker state: active, delayed, or offline;
- last heartbeat and last completed action;
- source count;
- queue counts by status;
- current freshness window;
- current minimum reactions and minimum views;
- recent publication and error events.

The worker writes a heartbeat at least once per minute. The panel reports
`delayed` after two missed intervals and `offline` after five. HTTP health alone
is not considered proof that the Telegram listener is working.

### Queue

Display cards containing:

- a small image preview or Telegram-provided video thumbnail;
- cleaned caption excerpt;
- source and original publication date;
- media type;
- views, reactions, forwards, and smart score;
- queue and action state;
- buttons appropriate for the state.

Available display sorting:

- newest first;
- reactions high to low;
- views high to low;
- smart score high to low.

Available filters:

- source;
- media type: any, video, or image;
- status;
- minimum reactions and minimum views for viewing only.

Changing queue sort or display filters never changes the automatic smart
selection algorithm.

Card actions:

- `Publish now`: request immediate publication of this exact item to the
  existing Telegram destination and MAX channel. This bypasses automatic
  engagement thresholds but not duplicate protection.
- `Skip`: atomically change a pending item to `skipped`.
- `Retry`: return a failed item to the pending queue after the existing safety
  checks.

The publish button becomes disabled while its action is pending or processing.
An item can have at most one active publish action.

### Sources

- List saved sources and their current availability.
- Add a public link, username, or supported invitation link.
- Remove a source from future collection without deleting its queue history.
- Request a scan with count, date range, media type, and source filters.
- Show each request as pending, processing, completed, or failed.

Joining a channel and scanning it are worker actions. The panel does not call
Telegram directly.

### Schedule and settings

- Add, edit, and remove publication slots.
- Configure time, media type, and optional source per slot.
- Edit the MAX signature label and URL.
- Edit the freshness window from 1 to 90 days.
- Edit global minimum reactions and minimum views for automatic publication.
  A value of `0` disables that threshold.

Before automatic selection, the worker refreshes live metrics and keeps only
pending items meeting both enabled thresholds. Manual publication may select an
item below the thresholds.

### Activity

Show action history and publication errors with timestamps, action type, item
or source, result, and a safe error message. Secrets and session data must never
be written to this log.

## Database additions

Extend `automation_queue` additively with:

- `caption_excerpt`;
- `views_count`;
- `reactions_count`;
- `forwards_count`;
- `preview_mime`;
- `preview_data` containing a bounded JPEG/WebP thumbnail.

Add `automation_actions` with:

- unique action ID;
- action kind and JSON payload;
- `pending`, `processing`, `completed`, or `failed` status;
- result or safe error text;
- created, claimed, and completed timestamps;
- an optional queue item ID;
- a uniqueness guard preventing two active publish actions for one item.

Reuse `automation_settings` for `min_reactions`, `min_views`, worker heartbeat,
and the last action summary. Existing queue rows remain valid with zero metrics
and no preview until refreshed.

Schema creation remains idempotent and runs from the existing state layer. No
destructive migration is required.

## Worker changes

- Capture separate metrics and a bounded preview when posts enter or refresh in
  the queue.
- Poll and atomically claim dashboard actions.
- Execute Telegram/MAX actions through the existing controller and publisher.
- Record action completion or a safe failure without losing the request.
- Update the worker heartbeat independently of scheduled publications.
- Apply automatic minimum thresholds after refreshing live metrics and before
  smart top-five selection.
- Keep current fingerprint, queue-state, and target-history duplicate guards.

If Render is asleep, actions stay visibly pending. Vercel never reports an
action as published until the worker records completion.

## API boundaries

All routes require authentication except login and logout:

- session: login, logout, current session;
- overview and activity reads;
- paginated queue read, filters, sorting, and preview delivery;
- queue skip, retry, and publish request;
- sources read, add/remove request, and scan request;
- schedule read/write;
- settings read/write.

Server responses contain only fields needed by the interface. Database errors
return a request ID and a generic message; detailed safe diagnostics remain in
server logs.

## Interface behavior

- Russian interface, responsive for desktop and mobile.
- Buttons show pending state immediately and cannot be double-submitted.
- Queue and action states refresh automatically without a full page reload.
- Empty, sleeping-worker, and failed-action states are explicit.
- Preview failure falls back to a media-type placeholder and never blocks queue
  management.

## Verification

Python tests cover:

- additive schema migration;
- metric persistence and preview limits;
- engagement threshold behavior;
- manual threshold bypass;
- atomic action claiming and duplicate publish prevention;
- action failure and recovery;
- heartbeat updates.

Dashboard tests cover:

- password and cookie handling;
- route authorization and origin checks;
- queue sorting and filtering;
- settings validation;
- publish, skip, retry, source, scan, and schedule requests;
- pending and error UI states.

Release checks include Python tests and compilation, dashboard tests, lint,
typecheck, production build, desktop/mobile browser smoke tests, a live Vercel
login, a harmless live status read, and one controlled manual publication only
when explicitly approved for production verification.

## Deployment

- Push both worker and dashboard code to the existing GitHub repository.
- Keep Render attached to the repository root Dockerfile.
- Create a Vercel project whose root directory is `dashboard/`.
- Configure only `DATABASE_URL`, `ADMIN_PASSWORD_HASH`, and `AUTH_SECRET` in
  Vercel.
- The password hash is generated locally from the password chosen by the owner;
  the plain password is never committed.
- Deploy the worker database/action changes first, then deploy the panel.
