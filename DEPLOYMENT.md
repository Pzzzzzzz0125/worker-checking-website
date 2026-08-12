# Deployment and Operations Runbook

Production deployment, integration, recovery, and maintainer handoff for the
Speed Construction Workforce App.
Last reviewed against the code: **August 8, 2026**

This document is written for the person who inherits the application. It
assumes that person may not know Vercel, PostgreSQL, Lark, or this codebase yet.
Follow the order in this runbook and do not copy production secrets into Git,
chat, screenshots, or email.

## 1. What is connected to what

```text
GitHub production repository
    |
    | push/merge to configured production branch
    v
Vercel build and deployment
    |
    +-- React static files
    +-- Python serverless functions
    |
    +--> PostgreSQL (operational data and integration state)
    |
    +--> Lark custom app (OAuth + tenant API credentials)
    |      |
    |      +--> Lark Base (visible one-way mirror)
    |      +--> Lark Drive folder (imports and connected Sheet)
    |
    +--> Gemini API (AI extraction only)
```

Changing application code:

```text
commit -> push production repository -> Vercel deploy -> new website behavior
```

Changing a website record:

```text
website save -> PostgreSQL immediately -> Lark queue -> Base/Sheet later
```

Changing a Lark Work Log or spreadsheet cell:

```text
Lark edit -> no change in PostgreSQL -> no change in website
```

## 2. Current production inventory

| Resource | Current production reference |
| --- | --- |
| Website | `https://workforce-app-theta.vercel.app` |
| Health check | `https://workforce-app-theta.vercel.app/api/health` |
| Production repo | `https://github.com/Pzzzzzzz0125/workforce-app` |
| Hosting project | Vercel `workforce-app` project |
| Database | AWS RDS for PostgreSQL through `DATABASE_URL` |
| Lark app | Speed Construction Workforce App |
| Lark Base token | derived from configured Base URL, stored only in Vercel |
| Lark Drive folder | dedicated imports/exports folder |
| Connected workbook | Speed Construction Work Schedule |

Confirm these in the provider consoles during the handoff. Provider ownership
can change without a code commit.

The local repository has historically used these remotes:

```text
deploy  -> Pzzzzzzz0125/workforce-app
origin  -> parcelzz/workforce-app
legacy  -> Pzzzzzzz0125/worker-checking-website
```

Vercel should be connected to `Pzzzzzzz0125/workforce-app`. Confirm under
Vercel Project Settings -> Git. Choose one repository as the permanent
canonical source after handoff; mirrors do not deploy automatically unless a
separate integration is configured.

### Important: this historical local checkout

The existing intern checkout has equivalent changes on repositories whose
commit hashes differ because production changes were historically
cherry-picked. `main` and `deploy/main` may therefore have different ancestry
even when their files match. **Do not solve this with a force push.**

For long-term maintenance, clone the production repository fresh, branch from
its `main`, and use normal pull requests. If this historical checkout must be
used for one last release:

1. commit and push `main` to the non-production mirrors;
2. create a temporary branch from `deploy/main`;
3. cherry-pick the new commit;
4. push that temporary branch to `deploy` as `main`;
5. return to local `main`.

Always inspect the remote and deployed commit before promotion.

## 3. Accounts and ownership checklist

At least two permanent company administrators should have recovery access to:

- GitHub organization/repository;
- Vercel team/project and billing;
- PostgreSQL provider project and billing;
- Lark developer console app;
- Lark Base;
- Lark Drive folder and connected workbook;
- Gemini/Google AI project;
- domain/DNS account if a custom domain is added;
- approved password manager entry containing protected-page passwords.

For each service, record in the company password manager:

- owner/team name;
- console URL;
- recovery email;
- billing owner;
- secret rotation date;
- who may approve production changes.

Do not record raw secrets in this file.

## 4. Environment variables

Copy `.env.example` as the inventory. Configure secrets in Vercel Project
Settings -> Environment Variables.

### Core deployment

| Variable | Required | Meaning |
| --- | --- | --- |
| `APP_URL` | yes | stable production origin, no trailing slash |
| `SESSION_SECRET` | yes | signs OAuth state, login, and access-grant cookies; minimum 32 characters |
| `DATA_BACKEND` | yes | production should be `postgres` |
| `DATABASE_URL` | yes for PostgreSQL | TLS-enabled PostgreSQL connection URI |
| `APP_TIME_ZONE` | recommended | `America/Los_Angeles`; defaults to this value |

Generate a new session secret locally:

```bash
openssl rand -hex 32
```

Changing `SESSION_SECRET` immediately invalidates all login and protected-page
cookies. That is safe but signs everyone out.

### Lark login and administration

| Variable | Required | Meaning |
| --- | --- | --- |
| `LARK_APP_ID` | yes | Lark custom app ID |
| `LARK_APP_SECRET` | yes | Lark custom app secret |
| `LARK_OAUTH_SCOPES` | yes | currently `offline_access` unless the app configuration requires additional identity scopes |
| `LARK_ADMIN_OPEN_IDS` | yes | comma-separated Lark open IDs allowed to initialize/import/administer |
| `LARK_VERIFICATION_TOKEN` | only for event callback | validates incoming Lark callback payload |

Get the signed-in user's open ID after OAuth:

```text
https://<production-domain>/api/auth/me
```

Add only the `open_id` string to `LARK_ADMIN_OPEN_IDS`. Separate multiple IDs
with commas and no quotes.

This allowlist is the bootstrap and recovery Super Admin list. After deployment,
users open **Settings & access** once to register their Lark identity, then
request Entry user or Schedule manager access. A Super Admin approves requests
or assigns roles in the same page. Only an existing Super Admin can assign a new
Super Admin; ordinary users cannot request that role.

Schedule is restricted to Schedule managers and Super Admins. Every schedule
requires a date, active worker, Site, at least one Cost Code, and work task. Times are optional, but two
different Sites for the same worker on the same day are stored only as
`pending_approval`; they cannot become a confirmed schedule until a Schedule
manager resolves or approves the conflict. Pending rows are not copied into
Entry.

Site Management uses the same protected access as Worker Management. The first
request after this release creates the PostgreSQL `Sites` collection and seeds
the 68 unique verified addresses in `data/site-address-library.csv`. New Entry,
Schedule, and invoice Site suggestions come from active Site records rather
than scanning thousands of historical Location Entry rows.

After deploying a release that adds or changes Site fields, run the Lark Base
setup endpoint once as a configured Lark administrator so the one-way mirror
has the matching `Sites` table. This does not replace PostgreSQL as the source
of truth. In Site Management, future XLSX/CSV libraries can be merged or used
to replace the active library. Import -> **Extract Sites for review** finds
legacy Entry names and creates archived/unverified records for manual cleanup.

For direct Lark access-request and Schedule-conflict notifications, enable the
app's bot capability and grant either `im:message:send_as_bot` (send messages as
the app) or the broader `im:message` scope. Publish a new Lark app version after
changing capabilities or scopes. Every recipient must be in the app/bot's
available user scope. If messaging is unavailable, the access request or
pending Schedule remains stored; the Schedule UI reports the delivery failure.

### Protected pages

| Variable | Required | Meaning |
| --- | --- | --- |
| `WORKER_ADMIN_PASSWORD` | recommended | alternative Worker Management access |
| `PAYROLL_PASSWORD` | yes for sensitive report access | protects both Payroll Check and Site Check |
| `EXPORT_PASSWORD` | yes | protects exports/workbook controls |

Use unique passwords. Do not reuse a Lark password or database password.
Changing one invalidates new unlock attempts; existing signed grants can remain
valid for up to eight hours unless `SESSION_SECRET` is also rotated.

### Lark Base and Drive

| Variable | Required | Meaning |
| --- | --- | --- |
| `LARK_BASE_APP_TOKEN` | yes | Base app token from the Base URL |
| `LARK_DRIVE_FOLDER_TOKEN` | import/export required | folder token from Drive URL |
| `LARK_WORKBOOK_TOKEN` | optional override | existing connected spreadsheet token |
| `LARK_MIRROR_ENABLED` | yes for mirror | `true` only after PostgreSQL and Base schemas are ready |

The current adapters discover Base tables by exact table name. Old
`LARK_*_TABLE_ID` environment variables are not read by the current code and
can be removed after confirming the deployed version matches this repository.

The workbook token normally lives in PostgreSQL `workforce_settings`.
`LARK_WORKBOOK_TOKEN` is an optional override/recovery value.

### AI

| Variable | Required | Meaning |
| --- | --- | --- |
| `GEMINI_API_KEY` | only for AI Reading | server-side Gemini API key |

The current model constant is in `gemini_parser.py`. A future model/API change
must be tested because structured response syntax can change.

### Recommended environment selection

- **Production:** all production values.
- **Preview:** separate database and, ideally, separate Lark app/Base/folder.
- **Development:** local/test database and development credentials.

Never point Preview deployments at the production database unless the preview
is read-only and the responsible owner explicitly approves it.

When adding or replacing a Vercel environment variable, redeploy. Existing
deployments keep the values captured at build/deploy time.

## 5. PostgreSQL setup

### Provider selection

Production currently uses **AWS RDS for PostgreSQL**. The source-code adapter
also works with Neon or another PostgreSQL service. The best serverless
connection string is a TLS-enabled endpoint in the same or nearby region as
the Vercel functions; use a provider pooler when one is available.

Example form:

```text
postgresql://USER:URL_ENCODED_PASSWORD@HOST:5432/DATABASE?sslmode=require
```

URL-encode characters such as `@`, `:`, `/`, `?`, `#`, `%`, and spaces in the
username/password. Do not paste the real URI into an issue or README.

### Network requirements

- Vercel functions must be able to reach the database hostname and port.
- Require TLS (`sslmode=require`).
- A database restricted to one office IP will reject Vercel's changing
  serverless egress addresses.
- Prefer the provider's pooled/serverless endpoint.
- Avoid permanently exposing an RDS instance to `0.0.0.0/0` with a weak
  password. If broad network access is unavoidable, use TLS, a long rotated
  password, least-privilege database user, monitoring, and provider controls.

### Physical schema

`POST /api/database/setup` creates:

- `workforce_tables`;
- `workforce_records`;
- `workforce_sync_outbox`;
- `workforce_lark_mirror_keys`;
- `workforce_settings`;
- required indexes and logical table registry rows.

The operation is idempotent.

### First initialization while copying from Lark

1. Configure a new PostgreSQL `DATABASE_URL`.
2. Set `DATA_BACKEND=lark`.
3. Set `LARK_MIRROR_ENABLED=false`.
4. Redeploy Production.
5. Sign in with a Lark open ID in `LARK_ADMIN_OPEN_IDS`.
6. Open the browser Developer Tools console on the production site.
7. Run:

```javascript
fetch("/api/database/setup", {
  method: "POST",
  headers: {"Content-Type": "application/json"},
  body: JSON.stringify({
    confirm: "INITIALIZE POSTGRES",
    copy_from_lark: true
  })
}).then(async response => ({
  status: response.status,
  body: await response.json()
})).then(console.log)
```

8. Verify `ready: true` and nonzero expected counts.
9. Compare Workers, Work Days, Location Entries, Cost Centers, Payroll Checks,
   and Audit Log with Lark.
10. Change `DATA_BACKEND=postgres`.
11. Redeploy Production.
12. Open `/api/health` and confirm:

```json
{"ok":true,"service":"speed-construction-workforce","data_backend":"postgres"}
```

### Initialize schema without copying Lark

For a PostgreSQL database that already contains the correct production records
but needs newer integration tables:

```javascript
fetch("/api/database/setup", {
  method: "POST",
  headers: {"Content-Type": "application/json"},
  body: JSON.stringify({
    confirm: "INITIALIZE POSTGRES",
    copy_from_lark: false
  })
}).then(response => response.json()).then(console.log)
```

Do not use `copy_from_lark:true` after PostgreSQL becomes authoritative unless
you have proven Lark is the intended recovery source. The importer upserts
logical keys and could replace newer PostgreSQL values with stale Lark values.

### Read-only setup status

As an authenticated admin:

```javascript
fetch("/api/database/setup")
  .then(response => response.json())
  .then(console.log)
```

The response includes backend, readiness, missing tables, and logical counts.

## 6. Lark custom app configuration

Lark console names can change. Search permissions by capability and verify that
the published version grants the APIs used below.

### Required capabilities

The server calls:

- tenant access token API;
- Base app metadata/list tables;
- Base create table;
- Base list/create fields;
- Base list/create/update/delete records;
- Drive list children in the configured folder;
- Drive file download;
- Drive Sheet export task/download for online Sheets used as imports;
- Sheets create spreadsheet;
- Sheets read metadata;
- Sheets add/delete worksheets;
- Sheets values read/write/batch update;
- Sheets formatting and dimension APIs;
- OAuth authorization-code exchange and user identity.

Enable the least-privilege tenant-token scopes covering Base metadata, tables,
fields, views/records, Drive folder/file access, and Sheets read/write.
Enable OAuth/basic user identity plus `offline_access` for user login. Publish a
new app version after changing scopes; “To be published” permissions do not
apply to production.

### Availability

Set the Lark released-version Availability scope to only the company users or
groups who should sign in. Being a Base collaborator is not the same as being
allowed to authorize the custom app.

If a user sees:

```text
You don't have access to "<app name>"
```

add that user/group to the app version's Availability scope and publish/release
the change.

### Redirect URL

Configure this exact OAuth redirect URL:

```text
https://workforce-app-theta.vercel.app/api/auth/lark/callback
```

For a replacement production domain, use:

```text
https://<stable-production-domain>/api/auth/lark/callback
```

It must exactly match `APP_URL` plus `/api/auth/lark/callback`. Do not use a
temporary Vercel preview URL for production OAuth.

### Obtain app credentials

Copy App ID and App Secret from Lark Developer Console -> Basic Information /
Credentials. Save them only as Vercel secrets.

### Create/share Base

1. In Lark, create a Base owned by a durable company account.
2. Open its URL. Example structure:

```text
https://<tenant>.larksuite.com/base/<APP_TOKEN>?table=<TABLE_ID>&view=<VIEW_ID>
```

3. Copy only `<APP_TOKEN>` to `LARK_BASE_APP_TOKEN`.
4. Give the released custom app access to the Base using the tenant's
   application/document permission mechanism. In some Lark tenants the app must
   be added through a group bot and that group added as a collaborator.
5. Confirm the app can read and edit the Base.
6. Add the environment variable and redeploy.

Do not copy the table token or view token as the Base app token.

### Initialize Base tables

After login as a configured administrator:

```javascript
fetch("/api/lark/setup", {
  method: "POST",
  headers: {"Content-Type": "application/json"},
  body: "{}"
}).then(async response => ({
  status: response.status,
  body: await response.json()
})).then(console.log)
```

The operation creates missing tables and fields and preserves existing data.
Review `warnings`; a same-named field with the wrong Lark type is not silently
replaced.

Read-only inspection:

```javascript
fetch("/api/lark/setup")
  .then(response => response.json())
  .then(console.log)
```

Expected tables and exact fields are defined in `api/lark/setup.py::SCHEMA`.
Do not manually rename them without changing code and migration tests.
Run the POST setup once after every release that adds fields to `SCHEMA`, before
processing the PostgreSQL-to-Lark mirror queue. This release adds location-hour
source, override, and audit fields used by entry editing.

### Lark event callback

Current production mirroring is one way from PostgreSQL to Lark. The event
callback is not needed to make website saves appear in Lark, and it deliberately
does not import direct Lark edits.

If event monitoring is retained:

```text
https://<production-domain>/api/lark/events
```

- choose **Event Subscriptions**, not card callback;
- subscribe to `drive.file.bitable_record_changed_v1` if required;
- configure `LARK_VERIFICATION_TOKEN`;
- leave Lark Encrypt Key empty because encrypted payloads are not implemented;
- GET returns endpoint information;
- URL verification POST returns the challenge as JSON;
- record-change events are acknowledged immediately.

Errors:

- “Response data is not valid JSON” means the route/deployment is wrong or an
  HTML 404 was returned.
- “Challenge code didn't get response” means the POST did not reach the
  deployed handler, verification token failed, or the deployed commit predates
  the endpoint.

## 7. Lark Drive imports

### Folder

Create a durable company-owned folder such as:

```text
Speed Construction Workforce Imports & Exports
```

Share only that folder with the app through the tenant's supported app/group
collaboration method. Copy the token from:

```text
https://<tenant>.larksuite.com/drive/folder/<FOLDER_TOKEN>
```

Set it as `LARK_DRIVE_FOLDER_TOKEN`.

Why a dedicated folder:

- limits the app's data exposure;
- prevents similarly named unrelated files from being imported;
- gives future maintainers one known place for controlled imports/exports;
- simplifies permissions and audit.

### Required import filenames

Place exactly one of each in that folder:

```text
2026 Worker's information - location standardized.xlsx
Cost Code and Cost Type Keep the Most Updated.xlsx
Speed Payroll.xlsx
```

The matcher tolerates harmless punctuation/extension differences and supports
native Lark Sheets by exporting them to XLSX. Missing or duplicate normalized
names fail preview rather than guessing.

### Preview

Use the Import page or:

```javascript
fetch("/api/lark/migration")
  .then(response => response.json())
  .then(console.log)
```

Preview must report `mode: "preview_only"` and `safe_to_write: true`. Review
counts, dates, total hours, warnings, and source file names.

### Staged import

The UI runs:

```text
workers -> cost_centers -> work_days -> location_entries -> audit
```

Each POST contains:

```json
{"confirm":"IMPORT VERIFIED PREVIEW","stage":"workers"}
```

Stages create only absent keyed records and can be safely resumed after a
timeout. Never run an import merely because a page is empty; first confirm the
active backend and database.

## 8. PostgreSQL-to-Lark mirror

### Enable safely

1. Ensure PostgreSQL is ready and authoritative.
2. Keep `LARK_MIRROR_ENABLED=false`.
3. Run database setup once with `copy_from_lark:false` to ensure the outbox,
   mapping, and settings tables exist.
4. Initialize Lark Base schema.
5. Set `LARK_MIRROR_ENABLED=true`.
6. Redeploy.
7. Queue an initial Work Log projection.

### Work Log backfill

```javascript
fetch("/api/sync/lark", {
  method: "POST",
  headers: {"Content-Type": "application/json"},
  body: JSON.stringify({
    work_log_backfill: true,
    limit: 500
  })
}).then(response => response.json()).then(console.log)
```

Repeat a normal drain until `pending` approaches zero:

```javascript
fetch("/api/sync/lark", {
  method: "POST",
  headers: {"Content-Type": "application/json"},
  body: JSON.stringify({limit: 500})
}).then(response => response.json()).then(console.log)
```

A full snapshot of all logical tables is available to admins with
`backfill:true`, but it is larger than a Work Log backfill and should be used
only for reconciliation.

### Status

```javascript
fetch("/api/sync/lark")
  .then(response => response.json())
  .then(console.log)
```

Important fields:

- `enabled`: mirror configuration;
- `pending`: pending plus processing rows;
- `retrying`: pending rows with a previous error;
- `synced_last_24h`;
- `last_synced_at`;
- POST additionally returns `processed`, `failed_tables`, and
  `snapshot_queued`.

Expected flow:

1. each PostgreSQL write queues an outbox row in the same transaction;
2. the browser starts a separate sync request after writes and startup;
3. a worker/day change rebuilds one consolidated Work Log row;
4. when configured, the corresponding Sheet cell is updated;
5. failures become pending for retry after 30 seconds.

Normal saves should succeed even if Lark is temporarily unavailable.

### Large backlog

If thousands of rows are pending:

1. confirm Lark scopes, Base access, and workbook access;
2. inspect `retrying` and Vercel logs for the actual Lark error;
3. drain in batches of 500;
4. wait for each request to finish before starting another;
5. confirm `pending` decreases and `failed_tables` is empty.

Do not delete the outbox merely to make the status look healthy.

## 9. Connected Lark spreadsheet

### Initialize

Sign in, unlock Export, and use the Export page. Equivalent request:

```javascript
fetch("/api/lark/workbook", {
  method: "POST",
  headers: {"Content-Type": "application/json"},
  body: JSON.stringify({action: "initialize"})
}).then(response => response.json()).then(console.log)
```

This creates **Speed Construction Work Schedule** in the configured Drive
folder, creates half-month sheets, writes workers/dates/cells, formats them,
and saves the token/row map in PostgreSQL.

### Refresh the same workbook

```javascript
fetch("/api/lark/workbook", {
  method: "POST",
  headers: {"Content-Type": "application/json"},
  body: JSON.stringify({action: "refresh"})
}).then(response => response.json()).then(console.log)
```

Refresh uses the stored token, so the link stays the same unless the workbook
was deleted or the configuration was replaced. It rebuilds the workbook and
reapplies:

- worker column width: about 190 px;
- work-date column width: about 300 px;
- header height: about 40 px;
- worker row height: about 120 px.

Manual size adjustments in Lark survive incremental cell updates but a full
refresh reapplies code-defined sizes.

### Recovery if configuration is lost

1. Do not create repeated workbooks blindly.
2. Find the existing spreadsheet token/URL.
3. Inspect `workforce_settings` key `lark_work_schedule`.
4. Restore the setting from database backup or set `LARK_WORKBOOK_TOKEN` as a
   temporary override.
5. Verify GET `/api/lark/workbook`.
6. Run refresh only after confirming it targets the correct file.

## 10. Vercel deployment

### First deployment

1. Import the production GitHub repository into Vercel.
2. Framework preset may be Other; `vercel.json` provides build/output settings.
3. Keep the repository root as project root.
4. Deploy once to obtain a stable production domain.
5. Configure the Lark redirect URL using that stable domain.
6. Add Production environment variables.
7. Redeploy.

Vercel executes:

```text
npm --prefix frontend ci
npm --prefix frontend run build
cp static/app-ui/index.html static/index.html
```

Static output directory is `static`.

### Routine deployment

1. Start from the production repository's current `main`.
2. Create a branch.
3. Make and test the change.
4. Push and review the Vercel Preview.
5. Merge/push the branch configured as Production in Vercel.
6. Watch deployment Build Logs.
7. Run production smoke tests.
8. Confirm data backend and mirror.

Do not assume pushing `origin` or `legacy` deploys Production. Vercel deploys
only the repository and branch configured in Project Settings -> Git.

Useful Git checks:

```bash
git status --short
git diff --check
git log -5 --oneline
git remote -v
```

Tests:

```bash
python3 -m unittest discover -v
npm --prefix frontend ci
npm --prefix frontend run build
```

The build output is ignored; do not force-add `static/app-ui`.

### Production smoke test

1. `/api/health` returns HTTP 200 and `data_backend: postgres`.
2. Sign in with an approved Lark user.
3. Overview loads and date filtering works.
4. Open Settings & access and confirm the signed-in Lark ID and role. For a
   non-admin test account, submit a request and approve it from a Super Admin
   account.
5. Daily Entry finds workers and cost codes for an Entry user or above; Viewer
   cannot save an Entry.
6. Save a controlled test record or use an approved existing record.
7. Reload and confirm persistence.
8. Payroll unlock and one pay period load.
9. Worker detail expands immediately below the row.
10. The same Payroll password grant opens Site Check and one known site
   loads.
11. Worker Management access behaves correctly.
12. Export access behaves correctly; generate one auditor report and one
    controlled invoice. Download and open both the invoice `.xlsx` and `.pdf`,
    then confirm their invoice number, customer details, and totals match.
13. `/api/sync/lark` shows no unexpected failures.
14. Lark Work Log/Sheet eventually reflects the controlled update.
15. Remove/revert the controlled test data through the application.

### Rollback code

Use Vercel Deployments -> select the last known-good production deployment ->
Promote/Rollback according to the Vercel interface.

A code rollback does not automatically roll back database records. If a bad
deployment wrote incorrect data, preserve evidence/backups and perform a
separate approved data repair.

## 11. Backup and recovery

### What must be backed up

The essential source of truth is PostgreSQL:

- `workforce_tables`;
- `workforce_records`;
- `workforce_sync_outbox`;
- `workforce_lark_mirror_keys`;
- `workforce_settings`.

Also retain:

- Vercel environment-variable inventory (not plaintext in Git);
- Lark app configuration and published scope list;
- original import workbooks;
- Lark Base/Sheet as secondary human-readable references;
- Git history.

Enable provider point-in-time recovery or scheduled backups appropriate to the
company's retention needs.

### Before a risky migration

1. announce a maintenance window;
2. prevent writes or tell users to stop entering data;
3. create and verify a PostgreSQL snapshot;
4. record logical counts and latest work date;
5. export/record current Lark mirror status;
6. test the migration on a copy;
7. execute Production;
8. reconcile counts and sample records;
9. reopen writes.

### PostgreSQL restore

1. stop or isolate production writes;
2. restore to a new database/branch when possible;
3. validate schema and counts;
4. compare records after the restore point;
5. update `DATABASE_URL`;
6. redeploy;
7. verify `/api/health` and setup status;
8. queue a Lark reconciliation only after PostgreSQL is confirmed correct.

Do not use Lark as an automatic recovery source without reconciling it; the
mirror may lag, direct edits are not authoritative, and deleted records may
differ.

## 12. Monitoring and routine operations

### Daily/weekly

- Verify the website opens and login works.
- Check critical entry and payroll flows after provider incidents.
- Inspect Lark sync status if the header says pending.
- Confirm database provider is healthy and within plan limits.

### Monthly

- Confirm backup/PITR is active.
- Review database storage and connection usage.
- Review Vercel function errors/duration.
- Review Gemini quota/errors.
- Review Lark app version, availability, and API errors.
- Remove departed staff from app availability and admin allowlist.
- Test restoration instructions on non-production resources.

### Before each payroll

- Confirm worker W-2/1099 classifications and rates.
- Confirm period 1–15 or 16–end.
- Inspect expanded worker histories.
- Review unusual overtime, double time, extra pay, off days, and missing cost
  centers.
- Confirm checked status is recorded.
- Treat estimates as review aids, not final payment instructions.

## 13. Troubleshooting

### “PostgreSQL schema is not initialized”

Possible causes:

- `DATABASE_URL` points to a different database/branch/environment;
- setup ran in Preview but Production uses another URL;
- schema transaction failed;
- Vercel deployment has stale environment variables.

Actions:

1. open `/api/health`;
2. verify the Production `DATABASE_URL` without exposing it;
3. redeploy after environment changes;
4. sign in as configured admin;
5. GET `/api/database/setup`;
6. run idempotent initialization with the correct `copy_from_lark` choice.

The old cloud-setup screen can mention Lark generically even when PostgreSQL is
selected; trust the specific error and health response.

### `ConnectionTimeout` / PostgreSQL unavailable

- confirm hostname, database, username, password, and URL encoding;
- require `sslmode=require`;
- confirm the provider allows Vercel network access;
- use the provider pooler;
- check region mismatch and provider sleep/cold start;
- inspect Vercel logs for function duration;
- rotate any credential exposed during troubleshooting.

### Application works locally but is slow on Vercel

Check in this order:

1. `DATA_BACKEND` is `postgres`, not `lark`;
2. database and Vercel are in compatible regions;
3. pooled endpoint is used;
4. Vercel function cold starts/duration;
5. endpoint payload size and full-table reads;
6. browser network timing;
7. Lark sync is separate and not blocking the request.

Vercel Hobby can have cold starts and limits, but upgrading does not eliminate
remote database latency, serial API calls, or oversized queries.

### Page returns `Request failed (404)`

- verify the route exists in `vercel.json`;
- verify `api/reports.py` dispatches its action;
- verify the pushed commit is in the Git repo connected to Vercel;
- inspect the deployed commit hash;
- redeploy without assuming a push to a mirror affects Production.

### Lark `Forbidden` / `RolePermNotAllow`

- publish the app version containing required scopes;
- give the application access to the specific Base/folder;
- confirm the Base/folder belongs to the expected tenant;
- confirm tenant-token permission rather than only user-token permission;
- sign in again after publishing if needed;
- inspect the returned `lark_code` and Vercel logs.

### “Lark created Workers without returning its table ID”

This historically occurred when the create-table response differed or
permissions were incomplete. Current setup handles the nested response shape.
Redeploy current code, publish permissions, rerun idempotent setup, and inspect
GET `/api/lark/setup`.

### Import says a workbook is missing

- verify it is directly inside the configured folder;
- verify exactly one normalized filename match;
- confirm the app can list/download it;
- confirm a native Sheet can be exported;
- do not create duplicate copies with the same title.

### Lark mirror has pending/retrying rows

- GET `/api/sync/lark`;
- inspect Vercel logs and `failed_tables`;
- verify Base/Sheet permissions;
- drain 500 at a time;
- verify counts decrease;
- do not switch `DATA_BACKEND` to Lark as a “sync fix.”

### AI Reading disabled/fails

- verify `GEMINI_API_KEY` in the active Vercel environment;
- redeploy;
- check Gemini quota/model availability;
- inspect Vercel logs without logging the pasted employee data or key;
- keep manual entry available;
- never bypass human review.

### User cannot log in

- verify the app is released;
- verify user/group is in Lark app Availability;
- verify redirect URL exactly matches production;
- verify `APP_URL`, App ID, App Secret, and session secret;
- use `/api/auth/logout`, then retry;
- inspect OAuth callback logs.

### Cost center looks filled but save says required

Cost-center text in the search input is not necessarily a selected center.
The UI stores selected centers as blue chips. If a future regression appears,
inspect selection/commit logic in `location-editor.tsx` and backend validation
in `entries.py`; do not weaken the required rule.

### Payroll hours and time range disagree

Historical imported time ranges were placeholders. The Payroll detail view
intentionally hides ranges and shows location plus allocated hours. New entry
ranges are validated at save. Do not use payroll display code to rewrite
historical entries.

## 14. Security and privacy

- Payroll rates, worker status, schedules, locations, and notes are sensitive.
- Restrict Lark app Availability.
- Restrict Base/folder collaboration.
- Use least-privilege database credentials.
- Keep TLS enabled.
- Never log API keys, cookies, database URLs, or pasted AI source text.
- Never expose protected passwords to frontend source.
- Rotate secrets after staff departure or accidental disclosure.
- Review `LARK_ADMIN_OPEN_IDS` immediately when an administrator leaves.
- Keep production and preview data separate.
- Use company-owned accounts rather than an intern's personal account.

Secret rotation order:

1. create replacement secret at provider;
2. update Vercel Production value;
3. redeploy and verify;
4. revoke old secret;
5. record rotation date in company password manager.

For `SESSION_SECRET`, users will be signed out. For `DATABASE_URL`, test the new
credential before revoking the old one.

## 15. Handoff acceptance checklist

The incoming maintainer should personally demonstrate:

- [ ] clone and build the repository;
- [ ] run all tests;
- [ ] create a Vercel Preview;
- [ ] locate Production logs and deployment commit;
- [ ] locate/edit Production environment variables;
- [ ] sign in through Lark;
- [ ] retrieve their open ID;
- [ ] access the PostgreSQL provider and view backups;
- [ ] explain why PostgreSQL is authoritative;
- [ ] inspect Lark sync status and drain a small batch;
- [ ] find the Base, Drive folder, Work Log, and connected workbook;
- [ ] add/edit/archive a test worker safely;
- [ ] save/clear a controlled entry;
- [ ] explain W-2 versus 1099 overtime behavior;
- [ ] unlock Payroll, Worker Management, and Export;
- [ ] preview import without writing;
- [ ] locate Gemini configuration;
- [ ] roll back a Preview/non-production deployment;
- [ ] identify who approves payroll and data restoration.

The outgoing maintainer should not consider handoff complete until:

- [ ] no critical service is owned only by a personal/intern account;
- [ ] two company administrators have recovery access;
- [ ] secrets are in the approved password manager;
- [ ] backup policy and restore owner are documented;
- [ ] Vercel's connected Git repository/branch is confirmed;
- [ ] the current Production deployment passes the smoke test;
- [ ] outstanding limitations in README are acknowledged.

## 16. Emergency decision guide

```text
Website unavailable?
  -> Check Vercel deployment and /api/health.

Health says postgres, pages fail?
  -> Check PostgreSQL reachability/schema/logs.

Website saves work, Lark is behind?
  -> Keep website available; repair/drain mirror separately.

Wrong payroll result?
  -> Stop payroll approval, preserve records, reproduce with tests,
     obtain payroll-owner approval before changing rules.

Possible data loss?
  -> Stop writes, snapshot database, compare backups, do not import or
     backfill until the authoritative state is identified.

Credential exposed?
  -> Rotate at provider, update Vercel, redeploy, revoke old credential,
     review logs/access.
```

For implementation details and the data model, return to
[README.md](README.md).
