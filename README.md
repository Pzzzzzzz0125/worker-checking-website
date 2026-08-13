# Speed Construction Workforce App

Maintainer handoff and implementation reference
Last reviewed against the code: **August 11, 2026**

## What this application is

The Speed Construction Workforce App is the company's shared system for
planning field work, recording what actually happened, and turning those work
records into information that operations and payroll can review. It replaces a
workflow that depended on large spreadsheets, inconsistent address names,
messages from multiple foremen, and repeated manual calculations.

In practical terms, the app answers four everyday questions:

1. **What is supposed to happen?** Schedule managers can plan which worker will
   go to which Site, on which date, for which task and Cost Code.
2. **What actually happened?** Entry users can record one day's workers, one
   worker's month, or use AI to turn a written field report into proposals.
3. **How should the work be reviewed?** Authorized users can inspect regular
   and weighted payroll hours, overtime, estimated labor cost, Site usage, and
   missing Cost Codes without rebuilding formulas in Excel.
4. **How is the information shared?** Administrators can generate auditor
   reports and invoices, while a one-way Lark mirror provides a familiar,
   human-readable spreadsheet view of saved work.

The app is intended for foremen, operations staff, payroll reviewers, and the
administrator responsible for workforce records. It is a workforce recording
and review tool; it is **not** a payroll filing service, accounting ledger,
time-clock, GPS tracker, or two-way Lark editor.

### What problem it solves

Without this app, the same information can appear differently in several
places: a Site may be written as `850 Villa`, `1260 = 850 villa =`, or a full
postal address; a worker may be referred to by an alias; and an eight-hour day
may be divided across several Sites and Cost Codes. The app gives these records
stable worker/date keys, validates new entries, preserves the historical text,
and resolves recognized Site aliases into a formal address for reporting.

The operational result is one traceable path:

```text
Plan upcoming work (Schedule)
        |
        v
Record and confirm actual work (Daily Entry / Worker Entry / AI Reading)
        |
        v
Validate Sites, Cost Codes, hours, time ranges, and overrides
        |
        v
Save authoritative records in PostgreSQL
        |
        +--> Overview, Payroll Check, and Site Check update from those records
        +--> Auditor reports and invoices can be generated
        +--> A background outbox mirrors the saved data to Lark
```

Planned Schedule rows and actual Entry rows are intentionally separate.
Scheduling a worker does not by itself add payroll hours. Only a confirmed work
entry becomes part of Overview, Payroll Check, Site Check, and payroll-oriented
exports.

### A typical day in the app

1. A Schedule Manager creates next week's assignments. Non-conflicting rows are
   confirmed; conflicting rows wait for approval.
2. After work is performed, an Entry User opens Daily Entry and records the
   actual Site, Cost Code, hours, overtime, extra pay, and notes. The user may
   instead update one worker across several dates in Worker Entry.
3. The backend validates the complete record and saves it to PostgreSQL. The
   same transaction queues a Lark mirror event, but the user does not wait for
   Lark to finish.
4. Overview and report pages read the new database record. Authorized payroll
   staff can check the worker, inspect the daily history, and mark the selected
   date range as reviewed.
5. An authorized user can download an auditor workbook or prepare an invoice.
   The connected Lark workbook is updated asynchronously as a visible copy.

The application was developed by **Zihao (Paul) Zhao** for Speed Construction,
an AlphaX company.

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
│   ├── sites.py                 formal Site address library, import, archive
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
│   ├── src/views/               checking, entries, data, transfers, workers, Sites
│   ├── src/lib/                 API client, types, utility functions
│   └── vite.config.ts           build and local API proxy
├── templates/                   approved auditor and invoice XLSX templates
├── data/site-address-library.csv initial verified Site address seed
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

## 4. Complete user and data workflows

This section follows the application from the user's point of view. Each page
description explains the action, validation, database effect, and downstream
effect. It is the first place to check when deciding whether a reported result
is expected behavior or a bug.

### 4.1 Sign in, startup, and navigation

1. The signed-out visitor clicks **Sign in with Lark**. Lark OAuth identifies
   the employee; the browser never receives the Lark App Secret.
2. The callback creates a signed, HTTP-only session cookie and returns the user
   to the single-page application.
3. `/api/bootstrap` loads the small essential set of active workers, Cost
   Codes, current identity, permissions, and configuration.
4. Site suggestions load separately through `/api/bootstrap_details`. A cached
   copy can be displayed first, so startup does not wait for every historical
   Location Entry.
5. The sidebar is filtered by role. Viewer-only users do not see Entry tools;
   only Schedule Managers and Super Admins see Schedule.
6. Page bundles load only when opened. A global spinner and button-level
   loading states tell the user when a request is still running.

Changing pages changes only the browser route (`#overview`, `#daily`, and so
on). It does not duplicate data. Daily Entry and Worker Entry keep unsaved
drafts in the same browser and warn before browser unload when possible.

### 4.2 Shared save workflow

Every normal business write follows this path:

```text
User clicks Save / Approve / Check / Archive
  -> frontend sends authenticated data
  -> backend verifies role or password grant
  -> backend validates the complete request
  -> one PostgreSQL transaction changes stable keyed records
  -> the same transaction queues Lark outbox events
  -> API returns the saved result
  -> the UI updates and Lark synchronization continues in background
```

PostgreSQL is authoritative. A slow or unavailable Lark API does not roll back
an otherwise successful database save. The header can therefore show **Saved ·
Lark sync pending**: the website record is safe, but its visible Lark copy has
not caught up yet. See Section 9 for mirror behavior.

### 4.3 Overview

**Purpose:** answer “how much work occurred in this period?” without opening
payroll detail.

1. Choose **From** and **To**, optionally type a worker, or select Last 7 days,
   This month, 1–15, or 16–end. The selected preset turns navy and displays a
   check. Manually changing a date creates a custom range.
2. Click **Apply**. A partial worker name must resolve to a real active worker;
   otherwise the page reports that no worker matched.
3. The page displays regular hours, weighted payroll hours, active workers,
   worked days, actual hours, average workday, off records, extra pay, and the
   latest worked date.
4. The lightweight Hours Trend groups a long range by day, week, or month.
   Blue is regular hours; amber is the additional payroll weight created by
   overtime and double time.
5. **Refresh** bypasses the five-minute page cache. Successful application
   writes also invalidate cached Overview results.

Overview is read-only. It calculates the chart and summary from Work Days and
worker metadata; it does not create checks or change recorded hours. Keeping
this API aggregated avoids downloading and rendering thousands of raw rows.

### 4.4 Payroll Check

**Purpose:** review a worker's work and estimated cost before payroll is
processed.

1. A Lark administrator enters automatically. Another authorized employee
   enters the shared Payroll password. A successful unlock creates a signed,
   user-bound eight-hour cookie and also unlocks Site Check.
2. Choose any From/To range, optionally filter one worker, or use the same four
   convenient presets as Overview. Click **Apply**.
3. The server also reads surrounding Monday–Sunday weeks, so W-2 weekly
   overtime stays correct when a selected range crosses a pay-period boundary.
4. The table shows classification, regular hours, weighted payroll hours,
   California overtime/double time, estimated cost, and worked dates. W-2 names
   are red; 1099 names are black.
5. Click a column header to sort and click again to reverse it.
6. Click a worker to expand their daily history immediately below the row;
   click the same worker again to collapse it. Detail includes Site and Site
   hours, Cost Codes, regular/OT/double-time/actual/weighted hours, daily cost,
   summaries by Site and Cost Code, missing Cost Codes as `--`, and matching
   total estimated costs. Historical time ranges are intentionally hidden.
7. Check a worker only after review. The app stores Checked, Checked By, and
   Checked At under a key containing that worker and the exact From/To range.
   Unchecking updates the same database record.

Opening, expanding, and sorting are read-only. The checkbox changes only
Payroll Checks; it does not change Entry hours. If an underlying Entry is later
edited, the calculated amounts change while the range-specific check remains,
so payroll staff should operationally review changed periods again.

Payroll is an estimate and must be reviewed by the company payroll owner.

### 4.5 Site Check

**Purpose:** answer “who worked at this Site, when, for how many hours, under
which Cost Codes, and at what estimated labor cost?”

1. Unlock with the same administrator/Payroll grant used by Payroll Check.
2. Search or select a Site and choose the report dates.
3. Historical labels are resolved at read time. A verified formal Site or alias
   is preferred; a unique compatible address/number is merged; otherwise the
   original historical label stays visible. Values containing `=` are
   preserved but can aggregate into a confirmed formal Site.
4. The page lists workers, regular and weighted payroll hours, first/last work
   date, estimated labor cost, and Cost Code distribution for that Site.
5. Column arrows sort the list. Clicking a worker opens that worker's detail
   for the selected Site; clicking again closes it.

Site Check is read-only. It joins Work Days, Location Entries, Workers, Cost
Codes, and formal Site mappings. It uses the same California weighting helper
as Payroll and reads surrounding weeks when needed. Formalization changes how
compatible labels group in reports; it does not rewrite historical work rows.

### 4.6 Daily Entry

**Purpose:** record several workers for one date.

1. Select a date. The server returns every active worker plus any saved Work
   Day and Site allocations for that date. Search changes only what is visible.
2. Editing creates a browser draft immediately. PostgreSQL and all report pages
   remain unchanged until Save. Returning to the same date in the same browser
   restores the draft; browser unload also produces a warning when possible.
3. Select **Worked** or **Off**. A worked day needs at least one Site and at
   least one Cost Code per Site. Enter or adjust each Site's Start, End, and
   Hours; then add overtime, extra pay, and notes when needed.
4. The first new Site begins with the standard 08:30/eight-hour defaults. Later
   Sites continue from the previous End and fill the remaining standard day.
   Users can change every value; linked time behavior is detailed in Section 5.
5. If official totals disagree with Site allocations or calculated overtime,
   the page shows the difference and requires an override reason before Save.
6. **Copy** captures one worker's draft in browser memory. **Paste** places it
   into another worker's draft; Paste alone does not write the database.
7. **Save** writes one worker. **Save all** writes every dirty worker. The
   backend validates the complete payload, then upserts one Work Day and its
   linked Location Entries. Successful drafts clear; failed ones remain visible.
8. **Clear record** requires confirmation and deletes the saved Work Day plus
   linked allocations. It is different from saving an Off day.

After Save, Overview, Payroll Check, Site Check, reports, and the Lark outbox
reflect the result. Saving an existing worker/date replaces that day's stored
allocations with the newly validated set; stable keys prevent duplicate days.

### 4.7 Worker Entry

**Purpose:** record or correct many dates for one worker.

1. Select an active worker and month. The server returns every date in that
   month, including blank dates, worked days, and Off days.
2. Edit a date with the same Site/Cost Code/time/hour editor and validation as
   Daily Entry. Drafts are stored by worker and month in this browser.
3. The sticky **Save edited** bar remains at the bottom of the viewport and
   saves all dirty dates. No payroll or report data changes before Save.
4. Select source dates and open Copy. Search and Select all help choose target
   workers; target dates can be a continuous range or individual dates.
5. Copying to the same worker on the same date is blocked because it has no
   useful effect and can conceal a selection mistake.
6. A valid copy can target other dates for the same worker, the same dates for
   other workers, or both. Existing target records are replaced only after the
   confirmation in the copy dialog.
7. The backend generates and validates each target worker/date through the
   normal Entry path. Copy cannot bypass required Cost Codes, active-worker
   checks, time rules, or numeric validation.

Saved database and downstream effects are identical to Daily Entry.

### 4.8 AI Reading

**Purpose:** turn an inconsistently formatted foreman message into reviewable
Entry proposals.

1. Paste the message and choose the intended year.
2. `/api/ai/parse` sends the text to Gemini from the Python backend; the API key
   remains server-side.
3. Gemini proposes workers, dates, Sites, hours, overtime, extra pay, and notes.
   The backend then matches names/aliases and Cost Codes against real app data.
4. The page shows confidence, warnings, proposed normalized values, and whether
   that worker/date already has a saved record.
5. The user corrects proposals, selects only the rows to apply, and confirms.
6. `/api/ai/apply` repeats normal Entry authorization and validation. Missing or
   ambiguous workers, invalid dates, missing required Cost Codes, or invalid
   allocations block the affected proposal.
7. Confirmed rows become ordinary Work Days and Location Entries and affect all
   reports exactly like manually entered work.

Gemini never writes directly to PostgreSQL and cannot bypass human review.

### 4.9 Schedule

**Purpose:** plan future assignments without prematurely creating payroll
records. Only Schedule Managers and Super Admins can open this page.

1. Choose **Single day** or **Multiple days**. Multiple-day mode supports a
   continuous range or individually selected dates. In range mode, the first
   calendar click sets Start, the second sets End, and included dates are
   highlighted. One submission can cover at most 31 dates.
2. Select an active worker, required Site, at least one required Cost Code, and
   required task. Start/End and notes are optional.
3. Save creates one stable Schedule row per worker/date. Non-conflicting rows
   are Confirmed.
4. An overlapping assignment for the same worker at another Site becomes
   **Needs approval**. The conflict and submitting identity are retained rather
   than silently confirming both assignments.
5. The form always includes every Super Admin as a required Lark recipient and
   lets the submitter select additional Schedule Managers. When a conflict is
   saved, one summarized Lark Bot message is sent with the worker, Site, task,
   Cost Codes, time, conflict details, submitter, and Schedule review link.
   Delivery is best-effort: the pending record remains saved if messaging
   fails, and the UI reports the sent and failed counts.
6. A Schedule Manager can approve or reject pending rows. Edit updates a row;
   Cancel retains it with Cancelled status. Reviewer identity remains available
   for accountability.
7. Weekly assignments can be searched by worker, Site, Cost Code, task, or
   status.

Schedule and Entry are intentionally separate. Schedule rows do not create Work
Days, payroll hours, Site costs, or Overview totals. Confirmed plans may be
copied into Entry in a later workflow, but only a real saved Entry counts as
actual work. Pending, rejected, and cancelled plans must never affect payroll.

### 4.10 Workers

**Purpose:** maintain worker identity and payroll metadata that Entry users
should not edit.

1. A Lark administrator enters automatically; another administrator uses
   `WORKER_ADMIN_PASSWORD`, producing a signed eight-hour grant.
2. Search/filter Active or Archived workers. Active management results are
   sorted by name.
3. **Add worker** accepts name, W-2/1099 type, daily salary/rate, display order,
   aliases, notes, and active state. The backend assigns an immutable numeric
   Worker Key and generates Normalized Name.
4. **Edit** changes the profile. Classification/rate changes alter future
   calculations and regenerated estimates for historical work because reports
   use the current profile, not a rate snapshot stored on every day.
5. **Remove/Archive** preserves the worker and all history but removes the
   person from operational Entry, AI, Schedule, Overview, Payroll, and Site
   lists.
6. Filter Archived workers and **Restore** to reactivate the same Worker Key and
   its existing history. Do not create a second profile to restore someone.

### 4.11 Site Management

**Purpose:** maintain the formal address book and connect inconsistent old Site
text to consistent report names. Access uses the same grant as Workers.

1. Search Active, Archived, or Needs Review Sites by name, address, city, ZIP,
   or alias.
2. **Add/Edit Site** stores display name, postal address components,
   semicolon-separated aliases, optional default Cost Code IDs, notes, Active,
   and Address Verified.
3. Saving refreshes future Entry, Schedule, invoice, and Site suggestions.
   Reports group compatible legacy aliases under the formal Site at read time.
4. **Archive** removes a Site from new Entry/Schedule selections while retaining
   history. **Restore** makes it selectable again.
5. Needs Review lists unmatched or ambiguous historical labels. **Formalize**
   starts a draft with the raw label as an alias; an administrator confirms the
   real address rather than accepting an uncertain guess.
6. Address-library XLSX/CSV **Merge** adds and updates. **Replace active
   library** also archives active Sites omitted from the file and requires an
   extra confirmation.

Formalization never rewrites old Location Entry text or hours. It changes
reference data, future choices, and report grouping.

### 4.12 Import

**Purpose:** perform a controlled, resumable historical bootstrap—not daily
recording.

1. Only identities in `LARK_ADMIN_OPEN_IDS` can open Import; there is no
   password fallback.
2. **Preview source files** reads the following configured Lark Drive files and
   makes no changes:
   - `2026 Worker's information - location standardized.xlsx`
   - `Cost Code and Cost Type Keep the Most Updated.xlsx`
   - `Speed Payroll.xlsx`
3. Preview displays worker/day/Site/Cost Code counts, date range, warnings, and
   a safe-to-write decision. A blocked preview disables Import.
4. **Import verified preview** requires confirmation and runs Workers, Cost
   Codes, Work Days, Location Entries, and Audit stages sequentially.
5. Each stage creates missing stable keys and preserves records already present.
   An interrupted run can be resumed by running Import again.
6. Site extraction scans the imported work and creates archived/unverified Site
   Management review items for uncovered historical labels.
7. **Extract Sites for review** can be run separately later. It creates only
   missing candidates and does not guess or save formal addresses.

A large import also creates a large Lark outbox backlog. Do not repeatedly run
Import because the mirror is still pending; monitor synchronization separately.

### 4.13 Export

**Purpose:** create controlled documents from saved records without changing
the source data. Export always requires `EXPORT_PASSWORD`, even for a Lark
administrator. Its signed, user-bound unlock expires after eight hours.

The chooser opens an independent setup page for each output:

**Connected work-schedule spreadsheet**

1. Open the existing Speed Construction Work Schedule or initialize/refresh it.
2. The workbook has half-month tabs, dates across row 1, workers in column A,
   and a normalized worker/date work block in each cell.
3. PostgreSQL stores the workbook token, so refresh keeps the same Lark link.
   A full refresh rebuilds content/formatting; normal Entry saves update affected
   cells asynchronously.

**Worker Compensation Auditor Report**

1. Choose inclusive From/To dates.
2. Search and explicitly select workers and Sites. The form starts with nothing
   selected. **Select all** turns every item blue and changes to **Clear all**.
3. Download remains disabled until at least one worker and Site are selected.
4. The server fills the approved XLSX template with matching worker/date/Site/
   Cost Code allocations, recorded time, total hours, and California regular/
   overtime allocation. The downloaded report does not mark payroll checked.

**Speed Invoice Template**

1. Fixed company/license/contact/footer values and the invoice number are
   automatic.
2. The user completes Bill To, Job Address, Description and Amount, Date,
   payment terms, Unit Price, and Amount. Saved Sites appear as Job Address
   suggestions, but a matching Site is not currently required.
3. Excel produces the approved editable workbook; PDF produces a print-ready
   document. Both use the same values and displayed invoice number for that
   form session.
4. Invoice generation downloads a document; it does not send email, create an
   accounts-receivable entry, or record payment.

Spreadsheet formatting comes from approved templates under `templates/`.
Invoice PDFs render on the server without Microsoft Office or LibreOffice.

### 4.14 Settings & access

**Purpose:** identify users automatically and manage role-based permissions.

1. Opening Settings reads the signed-in Lark identity and automatically
   registers its Open ID. Employees never type their own ID. The Copy button is
   available when an administrator needs the exact Open ID elsewhere.
2. The page shows Viewer, Entry User, Schedule Manager, and Super Admin levels,
   highlighting the current role.
3. A non-admin user selects a requested role, supplies a reason, and clicks
   **Send request**. The request appears immediately in every Super Admin queue;
   the app also attempts a Lark Bot message to Super Admins.
4. One pending request is allowed at a time. Its Approved/Rejected state and
   review note remain visible to the requester.
5. A Super Admin can approve/reject requests or directly change a registered
   user's role. The sidebar refreshes after the role changes.
6. Environment-listed recovery administrators cannot be demoted in the UI.
7. A Super Admin can click **Sync Cost Codes** to read the separately connected
   Lark Wiki Sheet, direct Sheet, or Excel file. The sync adds new IDs, updates the name/order for
   existing IDs, and reactivates matching archived IDs. Codes omitted from the
   source are retained so historical records are never damaged.
8. Vercel also runs the same idempotent, read-only-source sync once daily. The
   Cron route requires `CRON_SECRET`; it cannot be invoked anonymously.

Role changes affect future access, not historical records. Payroll/Site Check,
Worker/Site Management, Import, and Export have the additional grants shown in
Section 10; receiving Entry or Schedule access does not automatically reveal
sensitive payroll or export data.

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
| Schedules | `Schedule Key` | planned worker/date/Site/task, conflict state, submitter, and reviewer |
| Sites | `Site Key` | formal address library, aliases, verification, and active state |
| Audit Log | `Audit Key` | actor and old/new JSON for changes |
| Work Log | `Entry Key` | Lark-only consolidated worker/day projection |

Typical keys:

```text
Work Day Key       = <worker key>|<YYYY-MM-DD>
Location Entry Key = <work day key>|<location/allocation suffix>
Payroll Check Key  = <worker key>|<period start>|<period end>
Schedule Key       = SCH-<YYYY-MM-DD>-<generated suffix>
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
- Schedules
- Sites
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

### Role and access model

Opening **Settings & access** automatically registers the signed-in Lark open
ID; users never type an ID. New registered users start as `Viewer only` and can
request `Entry user` or `Schedule manager`. The request appears in the Super
Admin queue, and the app attempts a Lark direct message to every Super Admin.
Super Admin approval changes the role immediately. If the Lark Bot send scope
is unavailable, the request remains safe in the in-app queue.

Schedule conflicts use the same Bot API. Super Admins are mandatory recipients;
the submitting user may select additional Schedule Managers. Only registered
users whose current role can approve conflicts appear in that list, and the
backend validates every selected Open ID before sending.

The four hierarchical roles are:

| Role | Capability |
| --- | --- |
| Viewer only | view authorized non-editing pages |
| Entry user | Viewer plus Daily/Worker Entry, AI entry, and payroll check updates |
| Schedule manager | Entry access plus weekly Schedule creation and conflict approval |
| Super admin | full role approval/assignment and application administration |

`Super admin` cannot be self-requested. An existing Super Admin must assign it.
`LARK_ADMIN_OPEN_IDS` remains the bootstrap/recovery allowlist and always wins
over a stored role, so the application cannot demote its recovery administrator.
Roles and requests are stored in PostgreSQL tables `workforce_app_users` and
`workforce_access_requests`, which are created idempotently on first use.

Schedule records require a date, active worker, Site, at least one Cost Code,
and a work task. Schedule times are optional. A worker assigned to overlapping
different Sites is stored as `pending_approval` and cannot be confirmed until a
Schedule manager resolves the conflict.

| Capability | Requirement |
| --- | --- |
| Normal read-only pages | valid Lark session; registered role defaults to Viewer |
| Entry/AI writes and payroll checked-state changes | Entry user or above |
| Schedule creation and conflict approval | Schedule manager or above |
| Settings role approval/assignment | Super admin only |
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
| GET/POST | `/api/sites/library` | list/save formal Site library; management access |
| POST | `/api/sites/delete` | archive Site; management access |
| POST | `/api/sites/restore` | restore Site; management access |
| POST | `/api/sites/import` | merge/replace formal Site address file; management access |
| POST | `/api/sites/extract` | create Site formalization review candidates; management access |
| GET | `/api/payroll/access` | payroll authorization state |
| POST | `/api/payroll/unlock` | issue payroll password grant |
| POST | `/api/ai/parse` | Gemini proposal |
| POST | `/api/ai/apply` | validate and save selected proposals |
| GET | `/api/import/access` | admin-only import access state |
| GET | `/api/export/access` | export access state |
| POST | `/api/export/unlock` | issue export password grant |
| POST | `/api/export/template` | auditor `.xlsx` or invoice `.xlsx`/`.pdf`; export access |
| GET/POST | `/api/settings/access` | current role/request; apply/review/assign roles |
| GET/POST | `/api/schedule` | weekly assignments; conflicting rows require approval |
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

At this handoff, the Python suite contains **65 tests** with one workbook test
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

- Roles are intentionally limited to Viewer, Entry User, Schedule Manager, and
  Super Admin. There is not yet a separate Foreman role, per-Site permission,
  delegated approver list, or granular document permission model.
- Lark mirroring is triggered by app activity, not a dedicated continuous
  worker or cron. A closed app can leave pending rows until the next drain.
- The Lark event endpoint acknowledges callbacks but does not import Lark edits.
- Connected Lark Sheet and Work Log are reporting mirrors, not two-way editors.
- Schedule is a controlled planning record. It does not automatically create an
  actual Entry, create payroll time, or send reminders/messages yet.
- Site aliases improve report grouping but do not perform paid geocoding,
  distance calculation, routing, or address validation.
- Invoice generation creates files only; email, text, Lark delivery, payment
  tracking, and customer/contact management are future work.
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
