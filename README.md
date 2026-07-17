# Speed Construction Worker Schedule

Developed by Zihao (Paul) Zhao.

A local web app for searching worker hours, recording new work days, and safely
comparing Excel workbooks. The existing `2026 Worker's information.xlsx`
workbook is imported automatically on first run.

## Start the app

On macOS, double-click **Start FieldLedger.command**.

Or run:

```bash
python3 server.py
```

Then open [http://localhost:8000](http://localhost:8000).

The app has no external package dependencies. Data is stored locally in
`data/worklog.sqlite3`.

## Main workflows

- **Overview:** search a worker by name and choose a date range to view total hours, days worked,
  locations, extra pay, daily trends, and original Excel cell text.
- **Daily entry:** choose a date; new rows default to Worked and eight hours.
  Enter a required location and adjust the default hours when needed. Each row
  can be saved individually, and unsaved edits are protected as browser drafts
  across refreshes. Worked rows also record start time, end time, and a searchable
  list of one or more cost centers; times default to 8:30 AM and 4:30 PM.
  Cost-center choices come from columns B (ID) and C (name) of the current
  cost-code workbook. Each worker row has Copy and Paste controls for reusing
  one worker's information on another worker on the same Daily Entry page.
- **Worker entry:** choose one worker and one month to enter the same work
  information across every date. New dates default to Worked and eight hours,
  and use the same searchable multi-cost-center picker. Each day or all edited
  days can be saved.
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

## Parsing behavior

The parser is rule-based; AI is not required. It supports:

- `off` and annotated variants such as `off (holiday)`
- a single or multiple locations separated by `/`, `,`, or `+`
- location-level hours such as `432 (3h) + 1151 (5h)`
- total hours such as `1417 10 hours`
- overtime such as `669, OT 2 hours`
- additions such as `16970 (4hrs more)`
- extra pay such as `1545 ($20 more)`
- `half day` as four hours

The original cell text is always retained. Low-confidence entries are sent to
the confirmation queue instead of being guessed.

For detail reporting, explicitly entered location hours are preserved. Any
remaining daily hours are divided evenly among locations without specific
hours. Cost-center hours are divided evenly among the cost centers assigned to
that worker-day. Allocated values are rounded to two decimals.

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
