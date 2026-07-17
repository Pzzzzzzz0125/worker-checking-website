# Speed Construction Worker Schedule

Developed by Zihao (Paul) Zhao.

A local web app for searching worker hours, recording new work days, and safely
comparing Excel workbooks. The normalized
`2026 Worker's information - normalized.xlsx` workbook is the historical-data
source and export template.

## Start the app

On macOS, double-click **Start FieldLedger.command**.

Or run:

```bash
python3 server.py
```

Then open [http://localhost:8000](http://localhost:8000).

- Checking site: [http://localhost:8000](http://localhost:8000)
- Mobile logging site: [http://localhost:8000/log](http://localhost:8000/log)

The app has no external package dependencies. Data is stored locally in
`data/worklog.sqlite3`.

## Main workflows

The checking and logging experiences are separate web pages backed by the same
database. The logging page is optimized for a foreman using a phone.

- **Overview:** search a worker by name and choose a date range to view total hours, days worked,
  locations, extra pay, daily trends, and original Excel cell text.
- **Daily entry:** choose a date; new rows default to Worked and eight hours.
  Enter locations with semicolons (`444;111`) or include every location's hours
  (`432(3);1151(5)`). A live preview shows the exact Excel cell that will be
  saved. Overtime and extra pay have separate fields. Each row
  can be saved individually, and unsaved edits are protected as browser drafts
  across refreshes. Worked rows also record start time, end time, and a searchable
  list of one or more cost centers; times default to 8:30 AM and 4:30 PM.
  Cost-center choices come from columns B (ID) and C (name) of the current
  cost-code workbook. Each worker row has Copy and Paste controls for reusing
  one worker's information on another worker on the same Daily Entry page.
- **Mobile foreman log:** choose a date and worker, then add one or more
  locations. Every location requires at least one cost center and can have
  several. Worker/location/cost-center suggestions are ranked from past usage,
  and unfinished phone entries are protected as browser drafts.
- **Worker entry:** choose one worker and one month to enter the same work
  information across every date. New dates default to Worked and eight hours,
  and use the same searchable multi-cost-center picker. Each day or all edited
  days can be saved.
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

See [DEPLOYMENT.md](DEPLOYMENT.md) for the recommended PostgreSQL, object
storage, authentication, backup, and permission model before publishing online.

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
