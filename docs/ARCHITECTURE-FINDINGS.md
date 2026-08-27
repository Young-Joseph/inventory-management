# Architecture Findings — Handoff

**Repo:** `inventory-management` · **Branch:** `new_features` · **Base commit:** `27b0724`
**Investigated:** 2026-08-27 · **Companion doc:** [`docs/architecture.html`](./architecture.html)

Every claim below was measured against the working tree and probed against the running
services — not inferred from documentation. Line numbers are from commit `27b0724`; re-verify
if the tree has moved.

---

## Fix order

> **Not yet assigned.** The order is coming from outside this repo. Fill this in at the start of
> the next session before touching anything, so the sequence is recorded rather than remembered.

| # | Finding | Status |
|---|---------|--------|
| 1 | _(tbd)_ | |
| 2 | _(tbd)_ | |
| 3 | _(tbd)_ | |
| 4 | _(tbd)_ | |
| 5 | _(tbd)_ | |
| 6 | _(tbd)_ | |
| 7 | _(tbd)_ | |

---

## Summary

| ID | Finding | Severity | Blast radius |
|----|---------|----------|--------------|
| [F1](#f1) | Client calls six endpoints that don't exist (confirmed 404) | High | `api.js`, `App.vue`, backend routes |
| [F2](#f2) | Half-built purchase-order feature | Medium | `main.py`, `purchase_orders.json` |
| [F3](#f3) | `Reports.vue` bypasses the API client | Medium | `views/Reports.vue` |
| [F4](#f4) | `views/Backlog.vue` is unreachable | Medium | one file, delete or route it |
| [F5](#f5) | `total_backlog_items` ignores all filters | Low–Med | `main.py`, dashboard tile |
| [F6](#f6) | `Dashboard.vue` is 1271 lines | Low | large refactor, no behavior change |
| [F7](#f7) | Open CORS + no dev proxy | Low | `main.py`, `vite.config.js`, `api.js` |
| [F8](#f8) | Deprecated `uv` config + stray lockfile | Low | `pyproject.toml`, `server/` |

---

## F1 — Client calls six endpoints that don't exist {#f1}

**Severity:** High · **Confirmed live:** both paths return `404`

`client/src/api.js` defines six methods against two route prefixes the backend never registers.
`server/main.py` has **no non-GET route at all**.

| Method | `client/src/api.js` | Target | Live |
|--------|--------------------|--------|------|
| `getTasks()` | :77 | `GET /api/tasks` | 404 |
| `createTask()` | :82 | `POST /api/tasks` | 404 |
| `deleteTask()` | :87 | `DELETE /api/tasks/{id}` | 404 |
| `toggleTask()` | :92 | `PATCH /api/tasks/{id}` | 404 |
| `createPurchaseOrder()` | :97 | `POST /api/purchase-orders` | 404 |
| `getPurchaseOrderByBacklogItem()` | :102 | `GET /api/purchase-orders/{id}` | 404 |

**Call sites** — `client/src/App.vue`: `getTasks` :91 (via `onMounted(loadTasks)` :149),
`createTask` :99, `deleteTask` :120, `toggleTask` :138.

**Symptom is silent, not a crash.** `loadTasks` wraps the call in `try/catch` and only
`console.error`s (App.vue:92–95). Because `tasks` is a computed merge of
`currentUser.value.tasks` and `apiTasks.value` (App.vue:85–87), the modal still renders the
hard-coded mock tasks from `useAuth.js` while `apiTasks` stays empty. Add/delete/toggle appear
to do nothing except log. **Nothing looks broken on screen — check the browser console.**

**Verify:**
```bash
curl -s -o /dev/null -w "tasks:%{http_code}\n" http://localhost:8001/api/tasks
curl -s -o /dev/null -w "po:%{http_code}\n"    http://localhost:8001/api/purchase-orders
```

**Decision this fix requires:** build the backend routes, or remove the dead client methods.
Building them means introducing the first mutating endpoints in a service whose data is
module-level globals reloaded on every restart (see [Architecture note](#architecture-note)) —
writes will not survive a restart unless fixtures are written back to disk. That is a real
design decision, not a mechanical fix. Confirm the intended direction before starting.

---

## F2 — Half-built purchase-order feature {#f2}

**Severity:** Medium · **Type:** dead code

- `server/main.py:104` — `class PurchaseOrder(BaseModel)`, never used by any route
- `server/main.py:115` — `class CreatePurchaseOrderRequest(BaseModel)`, never used by any route
- `server/data/purchase_orders.json` — an **empty array**
- Only live consumer: `main.py:172–178`, which sets `has_purchase_order` on `/api/backlog` items
  via `any(po["backlog_item_id"] == item["id"] for po in purchase_orders)`. With an empty
  fixture this is **always `false`**.
- `client/src/components/BacklogDetailModal.vue` is the UI counterpart, reached from
  `Dashboard.vue:291`.

Overlaps with F1 (two of the six phantom endpoints are the purchase-order pair). **Sequence
these two together or decide F1 first** — fixing F1 by building routes largely resolves F2, and
fixing F1 by deleting client methods makes F2 pure deletion.

---

## F3 — `Reports.vue` bypasses the API client {#f3}

**Severity:** Medium · **Violates:** `client/CLAUDE.md` → "Centralize API calls in api.js"

`client/src/views/Reports.vue`:
- :128 — `import axios from 'axios'` (the only view that imports axios directly)
- :156 — `axios.get('http://localhost:8001/api/reports/quarterly')`
- :162 — `axios.get('http://localhost:8001/api/reports/monthly-trends')`

This is the **only** place the backend origin is duplicated outside `api.js:3`, so repointing
the app at a different backend currently means editing two files. Both endpoints work
(`200`); `api.js` simply has no wrapper for them.

**Fix shape:** add `getQuarterlyReports()` and `getMonthlyTrends()` to `api.js`, swap the two
call sites, drop the axios import. Low risk, self-contained.

> `.vue` file — per `CLAUDE.md`, delegate to the **vue-expert** subagent.

---

## F4 — `views/Backlog.vue` is unreachable {#f4}

**Severity:** Medium · **Size:** 152 lines

Neither registered in the router (`client/src/main.js:14–19` lists six routes, none of them
`/backlog`) nor imported by any component. `Dashboard.vue:186–210` renders its own inline
backlog table instead, and `BacklogDetailModal.vue` is wired from the Dashboard — so this view
looks like a superseded leftover rather than an unfinished feature.

**Decision:** delete it, or add the route. Confirm which — deleting is irreversible in the
working tree, though recoverable from git.

---

## F5 — `total_backlog_items` ignores all filters {#f5}

**Severity:** Low–Medium · **Real inconsistency, user-visible**

`server/main.py:200` — `total_backlog_items = len(backlog_items)`, computed from the
**unfiltered** module global and returned at :206.

Four of the five figures from `/api/dashboard/summary` respect the active filters
(`total_inventory_value`, `low_stock_items`, `pending_orders`, `total_orders_value`). This one
never changes as filters move, so the dashboard tile silently disagrees with its neighbours.

**This is not a one-line fix — verified.** `backlog_items.json` records have these keys only:

```
id, order_id, item_sku, item_name, quantity_needed, quantity_available, days_delayed, priority
```

There is **no `warehouse`, `category`, `status`, or `order_date` field on any backlog record.**
So piping `backlog_items` through `apply_filters` would match nothing and drop the count to
**0** for any active filter — worse than the current behavior. Three real options:

1. Add the missing fields to the fixture (and to `generate_data.py`, which regenerates it) —
   the only route to genuinely filterable backlog counts.
2. Join through `order_id` to `orders` (which *does* carry all four filter fields) and filter
   transitively.
3. Leave the value unfiltered and relabel the tile so it reads as a global total.

Pick one deliberately; option 1 or 2 is a data-model change, not a bug fix.

> Changing an aggregate that tests may assert on — check `tests/backend/test_dashboard.py`
> (13 tests) and use the **backend-api-test** skill for any test edits.

---

## F6 — `Dashboard.vue` is 1271 lines {#f6}

**Severity:** Low · **Type:** maintainability

Roughly a sixth of all frontend code (7344 lines across views + components + App.vue), against
the documented guideline in `client/CLAUDE.md` of extracting at 100 template / 150 logic lines.
It also repeats inline `style="cursor: pointer;"` across **8** table cells (`Dashboard.vue`
:191–206) that all share one `showBacklogDetail(item)` handler — a single row-level handler plus
one CSS class would replace all eight.

Large pure refactor with no intended behavior change. **Do not bundle this with a functional
fix** — it would make the diff unreviewable.

> `.vue` file — delegate to **vue-expert**.

---

## F7 — Open CORS and no dev proxy {#f7}

**Severity:** Low (demo context)

`server/main.py:52–53` — `allow_origins=["*"]` combined with `allow_credentials=True`.
Browsers reject that pairing for credentialed requests; it is only harmless here because
nothing sends credentials. There is no `server.proxy` in `client/vite.config.js`, which is
*why* the wildcard is needed — the browser calls :8001 cross-origin directly.

**Fix shape:** add a Vite proxy for `/api`, change `api.js:3` to a relative `/api` base, then
narrow `allow_origins` to `http://localhost:3000`. Touches three files and changes how every
request is routed in dev — **verify all six views still load** afterward.

---

## F8 — Deprecated `uv` config and a stray lockfile {#f8}

**Severity:** Low · **Type:** housekeeping

- `server/pyproject.toml` uses `[tool.uv]` → `dev-dependencies`. uv 0.12.6 warns on **every
  run**: *"the `tool.uv.dev-dependencies` field is deprecated and will be removed in a future
  release; use `dependency-groups.dev` instead."* Current spelling is a `[dependency-groups]`
  `dev` list. Harmless today, breaks on a future uv release.
- `server/package-lock.json` exists in a directory with **no** `package.json`. Confirmed
  **untracked** (`git ls-files` returns nothing) and it shows as `??` in `git status`, so
  deleting it is safe and touches no history. Note `client/package-lock.json` is gitignored
  deliberately (registry-leak guard, see root `CLAUDE.md`) — the `server/` one looks like an
  unrelated accident.

---

## Architecture note — read before any backend fix {#architecture-note}

`server/mock_data.py` loads all seven fixtures into **module-level globals at import time**
(mock_data.py:20–37). Route handlers close over those lists directly.

Consequences that constrain fixes:
- **No request can persist anything.** Any write endpoint mutates in-process state that dies
  with the process.
- **Editing `server/data/*.json` requires a backend restart** — Uvicorn runs without
  `--reload`.
- Restarting the backend resets everything to fixture state.

This is what makes F1 a design decision rather than a mechanical fix.

---

## Environment state (as left)

- **`uv` was not installed** at session start — this was the original blocker (`uv` is a Python
  tool from Astral; `npm install` never provides it). Installed via `brew install uv` → **0.12.6**.
- Both servers were started and verified: backend `http://localhost:8001` (`/docs` → 200),
  frontend `http://localhost:3000` → 200. They may no longer be running.
- **Working tree changes.** `git status` at handoff:
  - `M client/package.json` — **pre-existing, not mine.** Adds an `allowScripts` block
    (`esbuild@0.21.5`, `fsevents@2.3.3`), the signature of an allow-scripts install guard.
    Decide whether to commit or revert it before starting fixes, so it doesn't ride along in an
    unrelated diff.
  - `?? docs/architecture.html`, `?? docs/ARCHITECTURE-FINDINGS.md` — created this session.
  - `?? server/package-lock.json` — pre-existing, see [F8](#f8).
  - **No source file was modified this session.**

**Restart:**
```bash
cd server && uv run python main.py     # → :8001
cd client && npm run dev               # → :3000
cd tests  && uv run pytest             # 40 tests
```
Or the `/start`, `/stop`, `/test` skills.

---

## Repo conventions that constrain these fixes

From root `CLAUDE.md` and `client/CLAUDE.md`:

- **This repo and any fork are PUBLIC.** No credentials, internal hostnames, or private registry
  URLs. Leave `client/.npmrc` and the `client/package-lock.json` gitignore in place.
- **Any create/significant-modify of a `.vue` file → delegate to the `vue-expert` subagent.**
  Applies to F3, F4, F6.
- **Tests in `tests/backend` → use the `backend-api-test` skill.** Applies to F5, and to F1 if
  routes get built.
- **All GitHub operations → `mcp__github__*` tools** (exception: local branches via
  `git checkout -b`).
- **Browser testing → Playwright MCP** against :3000 and :8001.
- No emojis in UI. Unique `v-for` keys (`sku`, `month` — never `index`). Validate dates before
  `.getMonth()`.
- Standing instruction: **document non-obvious logic changes with comments** — explain *why*,
  not *what*.

---

## Baseline for regression checks

| Metric | Value |
|--------|-------|
| HTTP routes (all GET) | 14 |
| Write endpoints | 0 |
| Backend tests passing | 40 (17 misc + 13 dashboard + 10 inventory) |
| Routed views | 6 (+1 unreachable) |
| Components | 9 |
| Composables | 3 (all module-scoped singletons) |
| Fixture records | 351 — inventory 32, orders 250, transactions 56, demand 9, backlog 4, PO 0 |
| Frontend LOC | 7344 |

Endpoints returning `200`: `/`, `/api/inventory`, `/api/inventory/{id}`, `/api/orders`,
`/api/orders/{id}`, `/api/demand`, `/api/backlog`, `/api/dashboard/summary`,
`/api/spending/{summary,monthly,categories,transactions}`,
`/api/reports/{quarterly,monthly-trends}`.
Returning `404`: `/api/tasks`, `/api/purchase-orders`.
