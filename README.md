# Speed Construction Workforce App

Maintainer handoff and implementation reference
Last reviewed against the code: **July 28, 2026**

This repository contains the production workforce recording and payroll-review
website developed for Speed Construction. The application records daily work,
sites, cost codes, hours, overtime, and extra pay; provides payroll and
site summaries; manages worker profiles; imports the original 2026
workbooks; and mirrors operational data to Lark for people who prefer a visible
spreadsheet-style record.

The application was developed by **Zihao (Paul) Zhao**.

> This README explains how the software works. Use
> [DEPLOYMENT.md](DEPLOYMENT.md) for account setup, environment variables,
> deployment, database initialization, backup, recovery, and troubleshooting.

## 1. Production handoff summary

| Item | Current value or owner action |
| --- | --- |
| Production URL | `https://workforce-app-theta.vercel.app` |
| Production Git repository | `https://github.com/Pzzzzzzz0125/workforce-app` |
| Production branch | `main` |
| Additional code mirrors | `parcelzz/workforce-app` and `Pzzzzzzz0125/worker-checking-website` |
| Hosting | Vercel |
| Operational database | AWS RDS for PostgreSQL, connected through `DATABASE_URL` |
| Login provider | Lark custom app OAuth |
| Visible data mirror | Lark Base plus a connected Lark spreadsheet |
| AI extraction | Google Gemini, called only by the Python backend |
| Frontend | React 19, TypeScript, Vite, Tailwind CSS 4, shadcn-style components |
| Backend | Python serverless functions |

Before the current maintainer leaves, transfer or document ownership of:

1. the GitHub repository and branch protection;
2. the Vercel project and production domain;
3. the PostgreSQL provider/project;
4. the Lark custom application;
5. the Lark Base and Drive folder;
6. the Gemini/Google AI project and billing/quota contact;
7. the payroll, worker-management, and export passwords in the approved company
   password manager.

Never put real passwords, API keys, database URLs, payroll files, or employee
details in this repository.

## 2. Architecture

```text
Browser
  |
  | HTTPS + signed HTTP-only cookies
  v
Vercel
  +-- static/app-ui/*       React single-page application
  +-- api/*.py              small direct Python functions
  +-- api/reports.py        consolidated business API function
          |
          +--------------------------+
          |                          |
          v                          v
     PostgreSQL                 Lark / Gemini
     source of truth            external services
          |                          |
          | transactional outbox    +-- OAuth identity
          +------------------------->+-- Base Work Log mirror
                                     +-- connected Lark Sheet
                                     +-- Drive import files
                                     +-- Gemini text extraction
```

### Why `api/reports.py` exists

Vercel deploys every Python file under `api/` as a serverless function.
`vercel.json` rewrites most business routes to one dispatcher,
`api/reports.py`, to stay within Vercel Hobby function-count limits. The
dispatcher forwards the request to a module in `report_handlers/`.

### Source of truth

Production should use:

```text
DATA_BACKEND=postgres
```

The website reads and writes PostgreSQL. When `LARK_MIRROR_ENABLED=true`, the
same PostgreSQL transaction also creates an outbox event. A later request sends
those events to Lark.

This connection is intentionally **one way**:

```text
website -> PostgreSQL -> Lark Base / Lark Sheet
```

Direct edits in Lark Base or the connected Sheet do not return to PostgreSQL
and therefore do not change the website.

The code still supports `DATA_BACKEND=lark` as a migration/rollback adapter,
but direct Lark reads are much slower and should not be the normal production
configuration.

## 3. Repository map

```text
.
├── api/
│   ├── auth/                    Lark OAuth login, callback, identity, logout
│   ├── lark/                    Base setup, Drive migration, event callback
│   ├── _data_store.py           selects PostgreSQL or Lark adapter
│   ├── _postgres_base.py        PostgreSQL schema and generic record adapter
│   ├── _lark_base.py            Lark Base record adapter
│   ├── _lark_sync.py            asynchronous PostgreSQL-to-Lark mirror
│   ├── _lark_sheet.py           connected half-month Lark spreadsheet
│   ├── _work_log.py             consolidated human-readable Work Log format
│   ├── _reports.py              pay periods, report joins, overtime rules
│   ├── bootstrap.py             fast worker/cost-center app startup data
│   ├── bootstrap_details.py     deferred location metadata
│   ├── summary.py               lightweight Overview API
│   ├── reports.py               consolidated route dispatcher
│   └── health.py                public deployment health response
├── report_handlers/
│   ├── entries.py               daily/monthly entry read, save, clear, copy
│   ├── workers.py               worker CRUD and protected access
│   ├── payroll.py               half-month payroll calculation
│   ├── payroll_worker_detail.py expanded worker payroll history
│   ├── location_detail.py       location/cost-center/cost analysis
│   ├── exports.py               auditor and invoice template generation
│   ├── payroll_check.py         checked-state persistence
│   ├── ai.py                    review and apply Gemini proposals
│   ├── database.py              PostgreSQL initialization/copy
│   ├── sync.py                  mirror status, draining, and backfill
│   ├── workbook.py              connected spreadsheet initialize/refresh
│   └── data_access.py           Import/Export authorization
├── frontend/
│   ├── src/components/          shell, shared entry editor, UI primitives
│   ├── src/views/               checking, entries, data, transfers, workers
│   ├── src/lib/                 API client, types, utility functions
│   └── vite.config.ts           build and local API proxy
├── templates/                   approved auditor and invoice XLSX templates
├── worklog_parser.py            normalized legacy cell parser
├── xlsx_workbook.py             dependency-free XLSX reader/updater
├── gemini_parser.py             server-side Gemini structured extraction
├── test_*.py                    Python unit tests
├── vercel.json                  Vercel build/function/rewrite configuration
├── .env.example                 environment-variable inventory
└── DEPLOYMENT.md                operations and deployment runbook
```

Generated frontend files live in `static/app-ui/` and `static/index.html`.
They are built by Vercel and intentionally ignored by Git.

## 4. User-facing functions

### Overview

- Select a date range and optionally a worker.
- Shows compact totals and only the latest 50 activity records.
- Reads Work Days only. It deliberately does not load all site-entry records.
- Sites are loaded after initial startup by `bootstrap_details` and cached
  in browser local storage.

This design replaced a graph-heavy overview because repeated pagination of
thousands of Lark records made the deployed application feel stuck.

### Payroll check

- Protected by Lark administrator access or `PAYROLL_PASSWORD`.
- Selects a month and either day 1–15 or day 16–month end.
- Prioritizes actual hours, overtime, estimated payroll cost, days, and checked
  state.
- Clicking a worker expands the history immediately below that worker.
- The expanded table shows date, each site, allocated site hours, cost codes,
  regular hours, overtime, double time, actual hours, weighted hours,
  and estimated daily cost.
- Time ranges are intentionally hidden in payroll history because historical
  imports did not contain trustworthy ranges.
- Checked state is stored in `Payroll Checks`, not browser state.

Payroll is an estimate and must be reviewed by the company payroll owner.

### Sites

- Protected by the same Lark-admin/`PAYROLL_PASSWORD` grant as Payroll Check.
  Unlocking either page unlocks both for eight hours.
- Selects a site and date range.
- Shows workers, hours, days, first/last work date, cost codes, and estimated
  labor cost.
- Uses worker classification/rate and the same California weighting helper as
  payroll.
- Includes surrounding calendar weeks when calculating W-2 weekly overtime,
  even when the selected report range begins or ends in the middle of a week.

### Daily entry

- Choose one date and edit any number of workers.
- Worker search filters the page.
- Copy one worker's day and paste it to another worker.
- Save one worker or all dirty workers.
- `Clear record` deletes the saved Work Day and all linked Location Entries
  after confirmation.
- Unsaved drafts are kept in browser local storage for the selected date.
- A global loading indicator appears while API requests are active.

### Worker entry

- Choose one worker and one month.
- Edit several dates for that worker.
- Select all dates or selected dates.
- Copy selected dates to one or more workers.
- Search target workers in the copy dialog.
- Existing target records on those dates are replaced after confirmation.
- Newly changed blank days use the same default time behavior as Daily Entry.

### AI reading

1. The user pastes unstructured schedule text and chooses a year.
2. `/api/ai/parse` sends the text to Gemini from the server.
3. The response is matched against real workers and cost centers locally.
4. The page shows confidence, warnings, proposed values, and existing-record
   warnings.
5. The user edits/selects rows and explicitly confirms them.
6. `/api/ai/apply` validates the selected rows again and stores them.

Gemini never writes directly to the database. A missing or ambiguous worker,
date, location, or required cost center blocks that proposal.

### Worker management

- Protected by a configured Lark administrator or
  `WORKER_ADMIN_PASSWORD`.
- Active workers are the default list; archived workers are available through
  the dedicated Archived workers filter.
- Add a worker. The backend assigns the next stable numeric Worker Key.
- Edit name, W-2/1099 type, rate, display order, aliases, and notes.
- Worker Key is immutable; Normalized Name is generated by the backend.
- Archiving always preserves the worker profile and all historical records.
- Archived workers disappear from Overview, Payroll, Sites, AI, Daily
  Entry, and Worker Entry.
- Restore returns the worker to all operational pages without recreating or
  changing historical records.

### Import

- Restricted to Lark identities in `LARK_ADMIN_OPEN_IDS`; there is no password
  fallback.
- Reads exactly three files from the configured Lark Drive folder:
  - `2026 Worker's information - location standardized.xlsx`
  - `Cost Code and Cost Type Keep the Most Updated.xlsx`
  - `Speed Payroll.xlsx`
- Preview is read-only and reports counts, totals, date range, and warnings.
- Confirmed import runs resumable stages and creates only missing stable keys.
- This importer is a historical bootstrap tool, not the daily update path.

### Export

- Protected by `EXPORT_PASSWORD`, even for Lark administrators.
- The unlock cookie is signed, bound to the signed-in user, and expires in
  eight hours.
- The connected **Speed Construction Work Schedule** remains available as the
  one-way Lark spreadsheet mirror.
- **Worker Compensation Auditor Report** accepts From/To dates plus optional
  Site and Worker filters. It exports one row per worker/date/site/cost-code
  allocation, with recorded time, total hours, and California regular/OT
  allocation.
- **Speed Invoice Template** uses the same work filters and asks for Bill To,
  invoice number/date, payment due, and customer billing rate. The amount is
  selected labor hours multiplied by this billing rate. Worker payroll rates
  are intentionally never treated as customer billing rates.
- Both files are generated from the approved `.xlsx` templates in
  `templates/`; formatting is retained and the browser downloads the result.

## 5. Entry model and validation rules

### One day has two levels

```text
Work Day
  worker, date, status, daily totals, extra pay, notes
  |
  +-- Site Entry
  |     site, start/end, regular/OT allocation, cost code
  |
  +-- Site Entry
        ...
```

One visual site can generate multiple stored Location Entry rows when it has
multiple cost codes. The hours are divided across those rows while the UI
recombines them into one site.

> Terminology compatibility: the interface and this guide use **Site** and
> **Cost code**. Existing database tables and API payloads retain legacy field
> names such as `Location`, `Location Entries`, and `Cost Center ID`; renaming
> those persisted identifiers would break historical data and integrations.

### Required values

- Worked day: at least one site.
- Every worked site: at least one cost code.
- Off day: no site requirement and zero work hours.
- Cost-center options come from active `Cost Centers` records.

### Time and hour behavior

- A new first location defaults to `08:30–16:30` and 8 hours.
- A new second/subsequent location starts at the previous End and fills the
  remaining time toward 8 hours.
- Start, End, and Location Hours are linked:
  - changing Start preserves hours and moves End;
  - changing End recalculates hours;
  - changing Location Hours preserves Start and moves End.
- Location Hours are the normal source of truth. Changing a location's Hours,
  Start, or End immediately recalculates the Location Hours Sum, Total Hours,
  and calculated Overtime.
- Editing Total Hours creates a manual override; it does not redistribute or
  silently change location allocations.
- Editing Overtime creates a separate manual override.
- A mismatch displays the calculated and recorded values and offers reset
  controls.
- Saving a mismatch requires an override reason. The record preserves location
  sum, official total, difference, calculated/recorded overtime, source,
  reason, actor, and update time.
- Hour number inputs step by **0.5 hour**.
- If all time ranges are blank, a worked day defaults to 8 total hours.
- If any location uses time, all named locations need complete Start and End
  values.
- Ranges cannot end before they start or overlap.
- Each entered time range must match that location's Hours.
- Location ranges must not overlap.
- Total/Location or Overtime/calculated discrepancies are allowed only as
  explicit, reasoned manual overrides; invalid ranges and numeric values remain
  blocking errors.

Historical rows imported from the original workbook can have blank time ranges.
Do not manufacture ranges for old data merely to fill the UI.

### Multiple cost centers and rounding

A location may have several cost centers. The backend distributes regular and
overtime hours while preserving the original location total. Remainders are
placed into the final allocation, so an eight-hour location split three ways is
`2.67 + 2.67 + 2.66`, not `8.01`.

### Normalized text format

Legacy cells and visible mirrors use one normalized style:

```text
off
off (vacation)
444
444;111
432(3);1151(5)
669, ot 2h
1545, ex $20
1545, ot 2h, ex $20
```

- Semicolon is the location separator.
- A location without explicit allocation participates in the daily default of
  eight hours; it does not receive eight hours by itself.
- Parentheses after a location are that location's hours.
- `ot` is overtime.
- `ex $` is money and is never converted into hours.

The consolidated Lark Work Log contains a richer form:

```text
444 Pocatello [08:30-12:30 | 4h | CC: 100 Framing (4h)];
111 Main [12:30-18:30 | 6h (4h reg + 2h ot) | CC: 200 Electrical (6h)],
ot 2h, ex $20
```

## 6. Payroll rules implemented in code

`api/_reports.py::california_overtime` is the single overtime helper used by
payroll and location cost estimates.

### Classification

- `W2`: receives daily, weekly, and seventh-consecutive-day weighting.
- `1099`: actual hours are not automatically weighted by statutory overtime in
  this application.
- The imported payroll convention is **red name = W-2** and
  **black name = 1099**.

### W-2 calculation

- first 8 hours in a day: `1.0x`;
- hours over 8 through 12: `1.5x`;
- hours over 12: `2.0x`;
- regular hours beyond 40 in a Monday–Sunday week become `1.5x`;
- on the seventh worked day in the week, first 8 hours are `1.5x` and remaining
  hours are `2.0x`.

Pay-period boundaries do not reset a week. For a 1–15 or 16–end report, the
backend reads the complete surrounding Monday–Sunday weeks, computes overtime,
and returns only the selected pay-period dates.

Estimated pay is:

```text
weighted hours × (daily rate / 8) + extra pay
```

Amounts are rounded to two decimals after aggregation.

> This is application behavior, not legal advice. If the company's workweek,
> exemption rules, contractor classification, union agreement, or California
> requirements change, payroll management must approve corresponding code and
> tests.

## 7. Logical data model

| Logical table | Stable key | Purpose |
| --- | --- | --- |
| Workers | `Worker Key` | identity, classification, rate, aliases, active state |
| Work Days | `Work Day Key` | one worker/date status, official totals, and override metadata |
| Location Entries | `Location Entry Key` | location, recorded hours, cost center, range, and payroll allocation |
| Cost Centers | `Cost Center ID` | selectable cost-center reference |
| Payroll Checks | `Payroll Check Key` | checked state per worker/pay period |
| Audit Log | `Audit Key` | actor and old/new JSON for changes |
| Work Log | `Entry Key` | Lark-only consolidated worker/day projection |

Typical keys:

```text
Work Day Key       = <worker key>|<YYYY-MM-DD>
Location Entry Key = <work day key>|<location/allocation suffix>
Payroll Check Key  = <worker key>|<period start>
```

Do not change stable keys to array indexes or names. Worker names and display
order can change; keys provide idempotent imports, updates, deletes, and mirror
mapping.

## 8. PostgreSQL physical schema

The PostgreSQL adapter intentionally uses a generic JSONB record store so the
same report code can use either the Lark or PostgreSQL adapter.

### `workforce_tables`

Registry of logical tables. `table_name` is the primary key.

### `workforce_records`

```text
table_name   logical table
record_id    generated/internal record ID
key_field    logical key field name
key_value    stable logical key
fields       complete logical record as JSONB
created_at
updated_at
```

Primary key: `(table_name, record_id)`
Unique constraint: `(table_name, key_value)`

### `workforce_sync_outbox`

Transactional Lark mirror queue. Stores `upsert` or `delete`, attempt status,
retry time, lock time, error, and sync timestamp. Events that fail return to
`pending` after 30 seconds. A processing lease expires after five minutes.
Successfully synced rows are retained for seven days and then pruned.

### `workforce_lark_mirror_keys`

Maps each PostgreSQL `(table_name, key_value)` to its Lark `record_id`, avoiding
full-table searches before every mirror update.

### `workforce_settings`

Stores integration configuration that belongs with the database. The connected
workbook uses setting key `lark_work_schedule` for spreadsheet token, URL,
year, and stable worker-row assignments.

## 9. Lark representation

### Base tables

`POST /api/lark/setup` idempotently creates missing tables and fields:

- Workers
- Work Days
- Location Entries
- Cost Centers
- Payroll Checks
- Audit Log
- Work Log

It does not delete records or rename fields. Field definitions are in
`api/lark/setup.py::SCHEMA`.

### Consolidated Work Log

Work Days and Location Entries are projected into one searchable Lark row per
worker/date. Workers, Cost Centers, Payroll Checks, and Audit Log remain
separate because combining reference/security data with daily work would create
duplicates and ambiguous edits.

### Connected spreadsheet

The **Speed Construction Work Schedule** workbook contains:

- one worksheet for every half-month period;
- dates in row 1;
- worker names in column A;
- a normalized worker/date cell containing the complete work block;
- frozen headers, navy formatting, wide work columns, and tall rows.

The workbook token and row assignments are stored in PostgreSQL, so refreshes
continue using the same workbook link. `refresh` rebuilds it and reapplies the
application's sizes. Incremental website updates change only affected
worker/date cells.

## 10. Authentication and authorization

### Lark login

1. `/api/auth/lark/login` creates a signed OAuth state and stores it in a
   10-minute HTTP-only cookie.
2. Lark redirects to `/api/auth/lark/callback`.
3. The callback validates state and exchanges the code server-side.
4. The backend reads the Lark user identity.
5. A signed `workforce_session` HTTP-only, SameSite=Lax cookie is created for
   12 hours.

The Lark App Secret and access token never enter frontend JavaScript.

### Current access model

| Capability | Requirement |
| --- | --- |
| Normal pages and entry | valid Lark session |
| Payroll and Site Check | Lark admin or shared `PAYROLL_PASSWORD` grant |
| Worker management | Lark admin or `WORKER_ADMIN_PASSWORD` grant |
| Import/migration | Lark admin only |
| Export/workbook | `EXPORT_PASSWORD` grant |
| Base/PostgreSQL setup and backfill | Lark admin only |

Password grants are signed, user-bound HTTP-only cookies valid for eight hours.
Passwords are checked with constant-time comparison. `LARK_ADMIN_OPEN_IDS` is a
comma-separated server-side allowlist.

The Lark app's published availability controls who can log in at all. The Lark
Base collaborator list is separate from website access because server-side Base
calls use the app's tenant token.

## 11. API map

All business APIs require Lark login unless marked public.

| Method | Route | Purpose / extra authorization |
| --- | --- | --- |
| GET | `/api/health` | public backend selection check |
| GET | `/api/auth/lark/login` | start OAuth |
| GET | `/api/auth/lark/callback` | OAuth callback |
| GET | `/api/auth/me` | current session identity |
| GET | `/api/auth/logout` | clear session |
| GET | `/api/bootstrap` | workers and cost codes |
| GET | `/api/bootstrap_details` | deferred site metadata |
| GET | `/api/summary` | Overview range summary |
| GET | `/api/payroll` | pay-period totals; payroll access |
| GET | `/api/payroll_worker_detail` | expanded history; payroll access |
| POST | `/api/payroll_check` | update checked state; payroll access |
| GET | `/api/location_detail` | site/cost-code/cost analysis |
| GET/POST | `/api/day` | one-date entry load/save |
| POST | `/api/day/clear` | delete one worker/date and allocations |
| GET | `/api/worker-month` | month for one worker |
| POST | `/api/worker-days` | save selected worker dates |
| POST | `/api/worker-days/copy` | copy selected dates to target workers |
| GET/POST | `/api/workers` | list/save profiles; management access |
| POST | `/api/workers/delete` | archive worker; management access |
| POST | `/api/workers/restore` | restore archived worker; management access |
| GET | `/api/workers/access` | management authorization state |
| POST | `/api/workers/unlock` | issue management password grant |
| GET | `/api/payroll/access` | payroll authorization state |
| POST | `/api/payroll/unlock` | issue payroll password grant |
| POST | `/api/ai/parse` | Gemini proposal |
| POST | `/api/ai/apply` | validate and save selected proposals |
| GET | `/api/import/access` | admin-only import access state |
| GET | `/api/export/access` | export access state |
| POST | `/api/export/unlock` | issue export password grant |
| POST | `/api/export/template` | filtered auditor/invoice `.xlsx`; export access |
| GET/POST | `/api/lark/migration` | preview/staged historical import; admin |
| GET/POST | `/api/database/setup` | inspect/initialize PostgreSQL; admin |
| GET/POST | `/api/lark/setup` | inspect/initialize Base schema; admin on POST |
| GET/POST | `/api/sync/lark` | mirror status/drain/backfill |
| GET/POST | `/api/lark/workbook` | workbook status/initialize/refresh; export access on POST |
| GET/POST | `/api/lark/events` | optional Lark callback verification/ack |

When adding an endpoint, update both `api/reports.py` and the matching rewrite
in `vercel.json` if it is dispatched through the consolidated function.
Forgetting either side commonly produces `404 Request failed`.

## 12. Frontend data flow and perceived loading

`frontend/src/lib/api.ts` wraps `fetch`, converts non-2xx JSON responses to
`ApiError`, emits a global request-count event for the spinner, and triggers
background Lark sync after successful writes.

Startup is split:

1. `/api/bootstrap` returns the small essential worker/cost-center set.
2. cached location suggestions are used immediately when available;
3. `/api/bootstrap_details` loads location metadata in the
   background and refreshes local storage;
4. page bundles are lazy-loaded;
5. a small Lark sync request runs after the UI becomes usable.

This avoids blocking initial rendering on all Location Entries.

If production becomes slow again, first determine whether the delay is:

- Vercel cold start;
- PostgreSQL connection latency/region mismatch;
- an unindexed or full-record read;
- a large response/render;
- Lark mirror backlog;
- direct Lark backend accidentally enabled.

Do not assume upgrading Vercel fixes database/network design problems.

## 13. Local development

Prerequisites:

- Python 3.11 or newer;
- Node.js compatible with the checked-in frontend lockfile;
- access to a safe development PostgreSQL database;
- a development Lark app or explicit permission to use the production app.

Install/build the frontend:

```bash
cd frontend
npm ci
npm run build
```

For full local API work, use the Vercel CLI from the repository root:

```bash
vercel dev --listen 8000
```

In a second terminal, start Vite. Its development proxy expects the API at
port 8000:

```bash
cd frontend
npm run dev
```

Use a local `.env` copied from `.env.example`; `.env` files are ignored. Never
use production payroll data for casual UI development.

## 14. Testing and release checks

Python tests:

```bash
python3 -m unittest discover -v
```

Frontend type-check and production build:

```bash
npm --prefix frontend ci
npm --prefix frontend run build
```

At this handoff, the Python suite contains **62 tests** with one workbook test
skipped when the private payroll reference workbook is not present.

Before merging a change:

1. run the Python suite;
2. build the frontend;
3. verify no generated assets or secrets are staged;
4. review `git diff`;
5. deploy a Vercel Preview;
6. sign in and test the affected flow with non-sensitive test data;
7. check `/api/health`;
8. verify Production after merge;
9. confirm Lark sync status if the change writes data.

High-risk changes require focused manual checks:

- payroll/overtime: test a week crossing the 15th/16th boundary;
- entry validation: one/multiple sites and multiple cost codes;
- worker archive and restore, with and without history;
- schema/migration: run against a disposable database first;
- authentication: test signed-out, normal user, admin, and password grant.

## 15. Change guidelines

- Preserve stable key formats.
- Add or update tests for business rules.
- Use the `DataStore()` adapter rather than directly instantiating Lark in
  normal report/entry handlers.
- Keep PostgreSQL writes and outbox creation in the same transaction.
- Never make normal saves wait for Lark.
- Never accept AI output without local validation and human confirmation.
- Never infer historical time ranges that were not in the source.
- Treat worker classification and rates as sensitive payroll data.
- Avoid a second source of truth.
- Keep `.env.example`, this README, and DEPLOYMENT.md current whenever
  configuration or operations change.

## 16. Known limitations and future work

- Normal signed-in users do not yet have Foreman/Viewer roles; role granularity
  is limited to protected sections.
- Lark mirroring is triggered by app activity, not a dedicated continuous
  worker or cron. A closed app can leave pending rows until the next drain.
- The Lark event endpoint acknowledges callbacks but does not import Lark edits.
- Connected Lark Sheet and Work Log are reporting mirrors, not two-way editors.
- There is no automated browser end-to-end suite.
- Python runtime version is not explicitly pinned in repository configuration;
  verify Vercel's selected runtime before adopting version-specific features.
- Payroll remains an estimate; it is not a payroll filing or payment system.

## 17. Where to start when maintaining

For a UI or entry issue:

1. reproduce it in a Vercel Preview;
2. inspect `frontend/src/views/entry.tsx` and
   `frontend/src/components/location-editor.tsx`;
3. inspect validation/storage in `report_handlers/entries.py`;
4. add a regression test in `test_entries.py`.

For payroll:

1. inspect `api/_reports.py`;
2. inspect the relevant payroll handler;
3. add boundary tests in `test_reports.py`;
4. obtain payroll-owner approval.

For deployment/database problems:

1. read [DEPLOYMENT.md](DEPLOYMENT.md);
2. check `/api/health`;
3. verify Vercel Production environment variables;
4. verify PostgreSQL reachability and schema;
5. inspect Vercel function logs;
6. inspect `/api/sync/lark` separately from normal database health.

For data loss concerns, stop writes, preserve the database, and follow the
backup/recovery section in DEPLOYMENT.md before attempting a migration or
manual repair.
