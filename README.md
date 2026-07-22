# Speed Construction Worker Schedule

Developed by Zihao (Paul) Zhao.

A workforce web app for searching worker hours, recording work days, reviewing
payroll, and safely comparing Excel workbooks. Local development uses SQLite;
the production deployment is being prepared for Vercel with Lark Base storage
and Lark OAuth login.

## Start the app

On macOS, double-click **Start FieldLedger.command**.

Or run:

```bash
python3 server.py
```

The local command starts two connected development sites:

- Checking site: [http://localhost:8000](http://localhost:8000)
- Mobile logging site: [http://localhost:7001](http://localhost:7001)

The Python server has no external package dependencies. Both sites use the same
API code and store data in the same local `data/worklog.sqlite3` database, so a
saved logging entry is immediately visible on the checking site.

The main interface is built with React, TypeScript, Tailwind CSS, shadcn-style
components, TanStack Table, Recharts, React Hook Form, Zod, and Lucide icons.
Its compiled production files are committed in `static/app-ui`, so Node.js is
not required just to run the app. To change and rebuild the frontend:

```bash
cd frontend
npm install
npm run build
```

The previous vanilla interface remains available at
[http://localhost:8000/legacy](http://localhost:8000/legacy) as a fallback.

## Main workflows

The checking and logging experiences are separate web pages backed by the same
database. The logging page is optimized for a foreman using a phone.

- **Overview:** search a worker by name and choose a date range to view total hours, days worked,
  locations, extra pay, daily trends, and original Excel cell text.
- **Daily entry:** choose a date; new rows default to Worked and eight hours.
  Add structured location rows with optional allocated hours. Every location
  can optionally have one or several cost centers. A live preview shows
  the exact normalized Excel cell that will be saved. Overtime and extra pay
  have separate fields. Each row
  can be saved individually, and unsaved edits are protected as browser drafts
  across refreshes. Worked rows also record start time, end time, and a searchable
  list of one or more cost centers; times default to 8:30 AM and 4:30 PM.
  Cost-center choices come from columns B (ID) and C (name) of the current
  cost-code workbook. Each worker row has Copy and Paste controls for reusing
  one worker's information on another worker on the same Daily Entry page.
- **Mobile foreman log:** choose a date and worker, then add one or more
  locations. Each location can optionally have one or several cost centers.
  Worker/location/cost-center suggestions are ranked from past usage,
  and unfinished phone entries are protected as browser drafts.
- **Worker entry:** choose one worker and one month to enter the same work
  information across every date. It uses the same linked location, location-hour,
  and multi-cost-center rows as Daily Entry. Each day or all edited days can be
  saved. Select any combination of days, then copy them to one or more other
  workers when a crew worked together. The confirmation step names every
  destination worker and warns that existing entries on those dates will be
  replaced; the copy is saved as one transaction so it cannot be half-applied.
- **AI text entry:** paste flexible schedule notes and choose the year. After an
  explicit data-sharing confirmation, Google Gemini extracts worker/date records,
  locations, hours, overtime, times, and stated cost centers. Every proposed row
  remains editable and must be selected and confirmed before it is saved.
- **Payroll check:** choose either the 1–15 or 16–month-end pay period to see
  hours, overtime, days worked, and extra pay by worker. Pay rates and estimated
  totals are intentionally hidden; each worker can still be marked checked.
  Click a worker to see allocated hours and days by location and cost center,
  plus the number of workers using each cost center in that period.
- **Location check:** search a location and date range to see total workers,
  allocated hours, distinct work days, and each worker's hours, days, first work
  date, and last work date at that location.
- **Import & export:** upload a newer workbook to compare it with app data.
  Changes are shown before anything is applied. Export creates an updated copy
  of the original workbook while preserving its reference tabs, formatting, and
  parent-item columns.
- **Needs review:** confirm source cells that contain ambiguous locations such
  as `7??` or `-`.

## Normalized Excel cells

New app entries and exports use one canonical format:

- `off` and annotated variants such as `off (holiday)`
- `444` for one location and the default eight hours
- `444;111` for multiple locations sharing eight total hours
- `432(3);1151(5)` for an explicit location-hour split
- `669, ot 2h` for eight regular hours plus two overtime hours
- `1545, ex $20` for separate extra pay
- `1545, ot 2h, ex $20` when both annotations apply

Semicolon is the only location separator in normalized output. The importer
continues to understand legacy slash, comma, and plus separators so older
workbooks can still be upgraded safely.

The original cell text is always retained. Low-confidence entries are sent to
the confirmation queue instead of being guessed.

For detail reporting, explicitly entered location hours are preserved. Any
remaining daily hours are divided evenly among locations without specific
hours. Cost-center hours are divided evenly among the cost centers assigned to
that worker-day. Allocated values are rounded to two decimals.

The Gemini API key is read from the ignored local `data/gemini_api_key` file or
the `GEMINI_API_KEY` environment variable. The key is never returned to the
browser or committed to Git. AI Entry sends only the text deliberately pasted
into that page; it does not send the local worker roster or database. Do not
paste Social Security numbers, banking details, pay rates, or unrelated private
information.

See [DEPLOYMENT.md](DEPLOYMENT.md) for the Lark Base storage, authentication,
migration, and Vercel configuration before publishing online.

## Important data notes

- Only sheets named as half-month ranges (for example `Feb 1-15`) are treated
  as work logs.
- The latest half-month sheet supplies the active daily-entry roster.
  Historical workers remain searchable.
- Duplicate names in the same sheet are kept separate. The existing workbook
  has two different `Marcos` rows; the second is displayed as `Marcos (2)`.
- The current workbook only contains half-month tabs through July. The app can
  store later dates, but exporting those dates into new August–December tabs
  will require adding those tabs to the workbook template first.
