# Speed Construction Worker Schedule

Developed by Zihao (Paul) Zhao.

Speed Construction Worker Schedule is a workforce-recording and payroll-review
web application for Speed Construction. The current production version is a
responsive React application deployed on Vercel, authenticated with Lark OAuth,
and backed by Lark Base.

Production: [https://workforce-app-theta.vercel.app](https://workforce-app-theta.vercel.app)

## Current production architecture

```text
React + TypeScript browser application
             |
             v
Vercel static hosting and Python serverless APIs
             |
       Lark OAuth login
             |
             v
Managed PostgreSQL operational records
             |
      durable async mirror
             |
Lark Base visible tables
```

- The browser never receives the Lark app secret or tenant access token.
- The operational store is selected with `DATA_BACKEND`. `postgres` routes
  website reads and writes to AWS RDS, Neon, or another PostgreSQL provider.
- When `LARK_MIRROR_ENABLED=true`, PostgreSQL writes create durable sync tasks.
  The browser starts a separate batch sync after saves and on application
  startup, so normal page reads and save responses do not wait for Lark.
- Lark OAuth remains the website identity provider. Changing storage does not
  change who is allowed to sign in.
- Frequently repeated reads are cached briefly, while date-range reports use
  Lark-side filters instead of downloading the full historical dataset.
- Local SQLite files remain development/legacy resources and are not the
  production source of truth.

## Production workflows

### Overview

- Choose a date range and optionally a worker.
- Review total, regular, and overtime hours; active workers; worked/off days;
  average workday; extra pay; and latest activity.
- Search the latest 50 activity rows. Location and cost-center detail remains on
  the dedicated reporting pages so Overview needs only one filtered Base read.
- Returning to the same Overview filter reuses a five-minute browser cache
  unless an app write occurred or the user clicks Refresh.

### Payroll check

- Choose a month and either `1–15` or `16–month end`.
- Review actual hours, California-weighted hours, estimated salary cost,
  worked/off days, and checked status.
- Expand a worker directly below their row to see the payment-period work
  history, location allocation, cost-center allocation, and extra pay.
- W-2 workers receive daily/weekly/seventh-day California overtime weighting.
  Properly classified 1099 contractors remain straight-time in the application.
- Overtime calculation reads the complete workweek even when the week crosses
  a half-month payroll boundary.

Payroll values are estimates for review and are not a replacement for final
payroll or legal classification review.

### Location check

- Search a known location and choose a date range.
- See total workers, allocated hours, distinct work days, and the first/last
  recorded dates.
- Review each worker's hours, days, classification, and estimated labor cost at
  that location.
- Location estimates use the saved eight-hour daily rate, California-weighted
  overtime for W-2 workers, and straight time for 1099 contractors. Extra pay
  is excluded because it is not assigned to a specific location.
- Review the cost centers connected to the selected location.

### Daily entry

- Choose one day and update multiple workers.
- Search workers locally after the day loads.
- Record one or more locations for each worker.
- Each location supports:
  - its own optional start and end time;
  - editable location hours synchronized with its time range;
  - one or more required cost centers.
- The first location defaults to `08:30–16:30`. A newly added location starts
  at the previous location's End and fills the remaining time toward eight
  hours. Changing an automatically connected previous End updates the next
  range.
- Start, End, and Location Hours stay synchronized: changing Start preserves
  that location's Hours and moves End; changing End recalculates Hours; changing
  Hours preserves Start and moves End.
- If every location time is blank, a worked day defaults to eight hours.
- When location times are entered, all named locations require complete,
  non-overlapping ranges.
- Total Hours and Overtime remain visible and editable. Changing either value
  keeps the last location's Start and adjusts its End, so the location ranges,
  total, and overtime stay synchronized. Saving is blocked with a clear
  `Time conflict` message if imported or incomplete values still do not agree.
- Cost-center search selections are committed automatically. Blue chips show
  which centers are actually attached to the location.
- Copy/Paste reuses one worker's day information for another worker.
- `Clear record` appears after Save, confirms the action, and deletes both the
  Work Day and its linked Location Entries from Lark before resetting the row.
- Browser drafts protect unsaved Daily Entry edits across refreshes.

### Worker entry

- Choose one worker and one month.
- Edit multiple dates using the same location-time and cost-center rules as
  Daily Entry.
- Save one day or all edited days.
- Clear an individual date with the same confirmed `Clear record` action.
- Select or deselect every day in the loaded month with one button.
- Select multiple days and copy them to one or more workers when a crew shared
  the same schedule.
- Search the worker checklist inside the copy dialog before selecting targets.

### Worker management

- View the complete Workers master list and search by name, worker key, alias,
  or classification.
- Edit worker name, W-2/1099 classification, active status, daily salary/rate,
  display order, aliases, and private worker notes.
- Worker key remains read-only, and normalized name is regenerated when the
  worker name changes.
- Saved classification and rate changes flow into payroll estimates; saved
  names and active status refresh the entry-page worker lists.
- Access requires either a Lark identity listed in `LARK_ADMIN_OPEN_IDS` or the
  separate `WORKER_ADMIN_PASSWORD`. Successful password unlocks use an
  HTTP-only, user-bound cookie that expires after eight hours.

### Lark Drive migration

- The application can verify the three authoritative Lark Drive workbooks
  without changing Base records.
- Migration preview reports counts, date range, totals, and normalization
  warnings.
- Confirmed migration creates only missing keyed records and can safely resume
  by stage after interruption.
- The imported 2026 dataset currently includes Workers, Cost Centers, Work
  Days, and Location Entries in Lark Base.

The sidebar also contains AI Reading, Needs Review, and broader export surfaces.
Their complete production write/export APIs are still being integrated; do not
describe those screens as operational until their server routes are deployed
and verified.

## Time, location, and cost-center rules

- A worked day requires at least one location and every location requires at
  least one cost center.
- Location time ranges are optional only as a complete set: either all location
  times are blank, or every named location has both Start and End.
- Blank location times preserve the normalized default of eight total hours.
- Entered location ranges calculate the actual daily total.
- Ranges cannot end before they start or overlap another location range.
- Daily overtime must equal hours above eight when explicitly entered.
- Multiple cost centers divide a location's regular/overtime allocation without
  introducing rounding drift. For example, eight hours across three centers is
  stored as `2.67 + 2.67 + 2.66`, not `8.01`.
- New web entries do not store a day-level start/end range; time belongs to each
  Location Entry.

## Normalized work cells

The importer and display preview use one canonical format:

- `off`
- `off (vacation)`
- `444` — one location, default eight hours
- `444;111` — multiple locations sharing eight total hours
- `432(3);1151(5)` — explicit location-hour allocation
- `669, ot 2h` — eight regular hours plus two overtime hours
- `1545, ex $20` — separate extra pay
- `1545, ot 2h, ex $20` — overtime and extra pay together

Semicolon is the canonical location separator. Extra pay is never converted
into work hours. Low-confidence imported values remain identifiable for review
instead of being silently guessed.

## Authentication and access

- Anyone with the Vercel URL can reach the public sign-in surface.
- Workforce and payroll APIs require a signed Lark session.
- The Lark app's released-version **Availability scope** controls which Lark
  users can authorize login.
- Every currently authorized application user has the same normal entry and
  report capabilities; broader Admin, Foreman, and Viewer roles are not yet
  implemented.
- Worker Management, Base initialization, and Drive migration require a
  configured Lark administrator. Worker Management can also be unlocked with
  the separate server-side management password.
- Sessions are signed, HTTP-only, SameSite cookies with a 12-hour lifetime.

The Lark Base collaborator list is separate from website access. The server
uses the application's tenant token, so application authorization must remain
restricted to approved users.

## Local development

The current frontend requires Node.js for development:

```bash
cd frontend
npm ci
npm run build
```

The compiled assets are written to `static/app-ui`. They are generated during
the Vercel build and are intentionally excluded from Git.

Run the Python test suite with:

```bash
python3 -m unittest discover -v
```

## Deployment

Vercel builds the React frontend and deploys Python files under `api/` as
serverless functions. Report and entry routes are consolidated behind one
function to remain within the Vercel Hobby function limit.

Required production configuration includes:

- `APP_URL`
- `DATA_BACKEND`
- `DATABASE_URL` when PostgreSQL is selected
- `LARK_MIRROR_ENABLED` after the mirror schema has been initialized
- `LARK_APP_ID`
- `LARK_APP_SECRET`
- `LARK_OAUTH_SCOPES`
- `LARK_ADMIN_OPEN_IDS`
- `WORKER_ADMIN_PASSWORD` for optional password access to Worker Management
- `LARK_VERIFICATION_TOKEN`
- `LARK_BASE_APP_TOKEN`
- Lark Base table IDs
- `LARK_DRIVE_FOLDER_TOKEN`
- `SESSION_SECRET`
- `GEMINI_API_KEY` when AI endpoints are enabled

Gemini parsing runs only on the server. `/api/ai/parse` returns proposed records
for review, and `/api/ai/apply` writes only the records the user explicitly
confirms.

Never commit real secrets, payroll workbooks, private Drive exports, or local
SQLite databases. See [DEPLOYMENT.md](DEPLOYMENT.md) and
[.env.example](.env.example) for configuration details.

## PostgreSQL migration and Lark mirror

Connect AWS RDS, Neon, or another managed PostgreSQL service and configure its
TLS connection string as `DATABASE_URL`. Keep
`DATA_BACKEND=lark` until the initial copy is complete. Redeploy, sign in as a
configured Lark administrator, and call `POST /api/database/setup` with:

```json
{"confirm":"INITIALIZE POSTGRES","copy_from_lark":true}
```

The operation creates the PostgreSQL schema and upserts all six operational
tables from Lark Base. Verify the returned counts, then change
`DATA_BACKEND=postgres` and redeploy. After that switch, entries, payroll checks,
AI-confirmed rows, and worker updates use PostgreSQL.

Before enabling the visible Lark mirror on an existing PostgreSQL database,
upgrade the schema without re-importing stale Lark data:

```json
{"confirm":"INITIALIZE POSTGRES","copy_from_lark":false}
```

Then set `LARK_MIRROR_ENABLED=true` and redeploy. Future website writes are
queued transactionally in PostgreSQL and mirrored to Lark in a separate request.
To reconcile all existing PostgreSQL records once, an administrator can call
`POST /api/sync/lark` with:

```json
{"backfill":true,"limit":500}
```

The header reports `AWS and Lark synced`, `Syncing Lark`, or `Lark sync
pending`. Lark is a visible mirror; PostgreSQL remains the source of truth.

## Primary Lark Base tables

- **Workers** — stable worker key, name, active status, W-2/1099 type, rate, and
  display order.
- **Work Days** — worker/date status, total and overtime hours, extra pay,
  source, confidence, and notes.
- **Location Entries** — work-day key, location, per-location time range,
  regular/overtime allocation, and linked cost center.
- **Cost Centers** — cost-center ID, name, and active status.
- **Payroll Checks** — worker, payroll period, checked status, checker, and
  timestamp.
- **Audit Log** — reserved actor/action/entity history.
