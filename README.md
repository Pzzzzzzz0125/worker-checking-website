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
Lark Base workforce records + Lark Drive source workbooks
```

- The browser never receives the Lark app secret or tenant access token.
- Vercel functions read and update Lark Base on behalf of the application.
- Website changes are visible in Lark Base; Base changes appear after the
  website refreshes.
- Frequently repeated reads are cached briefly, while date-range reports use
  Lark-side filters instead of downloading the full historical dataset.
- Local SQLite files remain development/legacy resources and are not the
  production source of truth.

## Production workflows

### Overview

- Choose a date range and optionally a worker.
- Review total hours, active workers, worked/off days, extra pay, and daily
  workload.
- Search and sort the loaded work-record table.
- See locations, linked cost centers, and recorded location time ranges.

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
- Review each worker's hours and days at that location.

### Daily entry

- Choose one day and update multiple workers.
- Search workers locally after the day loads.
- Record one or more locations for each worker.
- Each location supports:
  - its own optional start and end time;
  - automatically calculated location hours;
  - one or more required cost centers.
- If every location time is blank, a worked day defaults to eight hours.
- When location times are entered, all named locations require complete,
  non-overlapping ranges.
- Total Hours and Overtime remain visible and editable. Saving is blocked with
  a `Time conflict` message when the location ranges, total, and overtime do
  not agree.
- Cost-center search selections are committed automatically. Blue chips show
  which centers are actually attached to the location.
- Copy/Paste reuses one worker's day information for another worker.
- Browser drafts protect unsaved Daily Entry edits across refreshes.

### Worker entry

- Choose one worker and one month.
- Edit multiple dates using the same location-time and cost-center rules as
  Daily Entry.
- Save one day or all edited days.
- Select multiple days and copy them to one or more workers when a crew shared
  the same schedule.

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
- Every currently authorized application user has the same normal view/edit
  capabilities; fine-grained Admin, Foreman, and Viewer roles are not yet
  implemented.
- `LARK_ADMIN_OPEN_IDS` restricts Base initialization and Drive migration, not
  normal entry or report pages.
- Sessions are signed, HTTP-only, SameSite cookies with a 12-hour lifetime.

The Lark Base collaborator list is separate from website access. The server
uses the application's tenant token, so application authorization must remain
restricted to approved users.

## Local development

The current frontend requires Node.js for development:

```bash
cd frontend
npm install
npm run build
```

The compiled production assets are written to `static/app-ui` and committed so
Vercel can serve the same verified build.

The repository also contains the earlier local Python/SQLite application:

```bash
python3 server.py
```

That server is useful for legacy/local inspection but does not reproduce the
production Lark-backed storage path.

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
- `LARK_APP_ID`
- `LARK_APP_SECRET`
- `LARK_OAUTH_SCOPES`
- `LARK_ADMIN_OPEN_IDS`
- `LARK_VERIFICATION_TOKEN`
- `LARK_BASE_APP_TOKEN`
- Lark Base table IDs
- `LARK_DRIVE_FOLDER_TOKEN`
- `SESSION_SECRET`
- `GEMINI_API_KEY` when AI endpoints are enabled

Never commit real secrets, payroll workbooks, private Drive exports, or local
SQLite databases. See [DEPLOYMENT.md](DEPLOYMENT.md) and
[.env.example](.env.example) for configuration details.

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
