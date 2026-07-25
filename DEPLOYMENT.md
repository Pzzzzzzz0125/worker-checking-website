# Vercel, PostgreSQL, and Lark deployment

Production uses one responsive Vercel website. Managed PostgreSQL (currently
AWS RDS or Neon) is the operational source of truth for worker, work-day,
location, cost-center, payroll-check, and audit records. Lark remains the OAuth
identity provider and provides one human-readable mirrored **Work Log**, one
Excel-style Drive spreadsheet, and small reference/control tables.

Set `DATA_BACKEND=postgres` after the initial Lark-to-PostgreSQL copy is
verified. Lark OAuth remains enabled for login. Normal operational reads do not
call Lark Base.

## PostgreSQL cutover

1. Configure a TLS-enabled `DATABASE_URL` for AWS RDS, Neon, or another managed
   PostgreSQL service.
2. Keep `LARK_MIRROR_ENABLED=false` during initial schema setup.
3. Keep `DATA_BACKEND=lark` initially and redeploy.
4. Sign in as a user listed in `LARK_ADMIN_OPEN_IDS`, and run the
   administrator-only `POST /api/database/setup` importer with confirmation
   `INITIALIZE POSTGRES`.
5. Compare the returned Workers, Work Days, Location Entries, Cost Centers,
   Payroll Checks, and Audit Log counts with Lark.
6. Set `DATA_BACKEND=postgres`, redeploy, and verify `/api/health` reports
   `postgres`.
7. Keep Lark Base unchanged during the test so rollback requires only changing
   `DATA_BACKEND` back to `lark`.

The application reads the standard PostgreSQL `DATABASE_URL`; no
provider-specific source-code adapter is required. Use a pooler when the
selected provider supports one.

## Visible Lark mirror

The mirror is intentionally asynchronous:

```text
Website save -> PostgreSQL transaction + outbox -> response to user
                                             |
                                             v
                                separate Lark batch sync
```

For an existing PostgreSQL database:

1. Deploy this schema with `LARK_MIRROR_ENABLED=false`.
2. Call `POST /api/database/setup` with confirmation `INITIALIZE POSTGRES` and
   `copy_from_lark:false`. This adds the outbox and Lark record-ID mapping
   tables without replacing PostgreSQL records.
3. Send an authenticated administrator `POST /api/lark/setup`. This creates
   the consolidated **Work Log** table and its fields idempotently.
4. Set `LARK_MIRROR_ENABLED=true` and redeploy.
5. Queue the initial consolidated reconciliation with authenticated
   administrator request `{"work_log_backfill":true,"limit":500}` to
   `POST /api/sync/lark`.

Every PostgreSQL upsert or deletion is committed with its outbox event. The
frontend starts sync in a separate request after writes and when the app opens.
Failed Lark calls stay pending and retry later. The app header exposes the
current mirror state. Lark Base should be treated as a visible, read-only
operational mirror; direct Lark edits do not update PostgreSQL.

## Deployment sequence

1. Import the private GitHub repository into a Vercel project.
2. Deploy once to obtain the stable production `.vercel.app` domain.
3. Add `https://<production-domain>/api/auth/lark/callback` to the Lark custom
   app's Security Settings. Do not use a changing preview-deployment URL.
4. Publish the Lark app version containing the OAuth, Base, and record-change
   permissions.
5. Add every value from `.env.example` under Vercel Project Settings →
   Environment Variables. Real secrets must never be committed to Git.
6. Redeploy the production branch.

The first deployment intentionally displays a cloud-setup screen until the
selected data adapter and environment variables are connected. The health
endpoint is `/api/health`.

## Authentication

`/api/auth/lark/login` starts Lark OAuth. The callback validates a signed,
short-lived state value before exchanging the authorization code on the
server. A successful login creates a signed, HTTP-only, SameSite=Lax session
cookie. The Lark app secret and access tokens never enter browser JavaScript.

The session secret must contain at least 32 random characters. Generate one
locally with:

```bash
openssl rand -hex 32
```

Use a restricted Lark app audience and enforce server-side roles before payroll
data is exposed. OAuth identifies the user; it does not by itself authorize
that user to view payroll.

After signing in, `/api/auth/me` returns the current user's Lark `open_id`.
Add the administrator's ID to `LARK_ADMIN_OPEN_IDS`, redeploy, then send an
authenticated `POST` request to `/api/lark/setup` to create any missing Base
tables and fields. The operation is idempotent: existing records and correctly
named fields are preserved. A signed-in user can use `GET /api/lark/setup` as a
read-only permission and schema diagnostic.

Worker Management uses the same Lark administrator list. To allow a second
password-based access path, add `WORKER_ADMIN_PASSWORD` in Vercel and redeploy.
The password stays server-side; successful unlocks use a user-bound HTTP-only
cookie that expires after eight hours.

The Import and Export pages use separate authorization:

- Import requires a signed-in Lark user whose open ID is in
  `LARK_ADMIN_OPEN_IDS`.
- Export requires `EXPORT_PASSWORD`; even administrators must unlock it. The
  export grant is a signed, user-bound, HTTP-only cookie that expires after
  eight hours.

## Lark Base structure

Use stable field names and do not delete or rename fields after integration.

- **Work Log:** the single visible working-information table, with one row per
  worker/day; it includes searchable columns and a complete normalized entry.
- **Workers:** stable worker key, display name, active status, W-2/1099 type,
  daily rate, and display order.
- **Cost Centers:** cost-center ID, name, and active status.
- **Payroll Checks:** worker, period start, checked status, checker, and time.
- **Audit Log:** actor, action, entity key, old/new values, and timestamp.

The operational PostgreSQL model still stores Work Days and Location Entries
separately so hours, time ranges, and multiple cost centers can be validated.
The mirror projects those related records into one Work Log row. Existing Lark
Work Days and Location Entries may be hidden only after reconciliation is
verified; do not delete them during rollout.

The browser never calls Lark directly. Vercel functions obtain a tenant token
and perform mirrored Base operations server-side. Website changes become
visible in Lark after the outbox sync completes. Direct Lark edits are not
returned to PostgreSQL.

## Connected Drive spreadsheet

Enable and publish the tenant-token `sheets:spreadsheet` permission before
initialization. Keep `LARK_DRIVE_FOLDER_TOKEN` configured. After deploying,
open the password-protected Export page and initialize the workbook once:

```json
POST /api/lark/workbook
{"action":"initialize"}
```

The endpoint creates **Speed Construction Work Schedule** in the configured
Drive folder, adds one worksheet per half-month period, writes the complete
historical worker/date matrix, and stores its token and stable worker rows in
PostgreSQL. It is idempotent; `{"action":"refresh"}` rebuilds the matrix in the
same workbook. `GET /api/lark/workbook` returns status and the workbook URL.

Once configured, work-day and worker-name outbox events update both Work Log
and the spreadsheet. Spreadsheet writes remain asynchronous and do not add
Lark latency to normal page reads or save responses. Treat the sheet as
read-only; direct cell edits are not imported into PostgreSQL.

The Export page also contains inactive slots for invoice (`发票`), report
(`汇报`), and additional form exports. Implement each as a separate generator
after its approved sample/template is available; do not overload the connected
schedule workbook with unrelated layouts.

## Migration and validation

Do not upload `data/worklog.sqlite3` or payroll workbooks to GitHub. A one-time
server-side migration will read the local SQLite database and batch-create Lark
records after the Base schema is finalized. Validate worker counts, work-day
counts, total hours, pay-period totals, and several individual histories before
switching production to Lark.

Keep a read-only local backup until the Lark totals and exports have been
reconciled. Payroll output is an estimate and should be reviewed against the
company's official workweek, worker classifications, and payroll rules.
