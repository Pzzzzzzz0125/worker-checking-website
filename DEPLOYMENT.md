# Vercel and Lark deployment

Production uses one responsive Vercel website. Lark Base is the source of truth
for worker, work-day, location, cost-center, payroll-check, and audit records.
The local Python server and SQLite database remain available only for local
development and data migration.

For the PostgreSQL performance comparison, the application can instead use AWS
RDS by setting `DATA_BACKEND=postgres`. Lark OAuth remains enabled for login,
but operational record reads and writes no longer call Lark Base.

## PostgreSQL cutover

1. Rotate any database password that has been shared in chat or source code.
2. Confirm the RDS instance requires TLS and is reachable from Vercel without
   exposing port 5432 broadly to the public internet.
3. Add `DATABASE_URL` in Vercel using `sslmode=require`. Keep
   `DATA_BACKEND=lark` initially.
4. Deploy, sign in as a user listed in `LARK_ADMIN_OPEN_IDS`, and run the
   administrator-only `POST /api/database/setup` importer with confirmation
   `INITIALIZE POSTGRES`.
5. Compare the returned Workers, Work Days, Location Entries, Cost Centers,
   Payroll Checks, and Audit Log counts with Lark.
6. Set `DATA_BACKEND=postgres`, redeploy, and verify `/api/health` reports
   `postgres`.
7. Keep Lark Base unchanged during the test so rollback requires only changing
   `DATA_BACKEND` back to `lark`.

Serverless functions can open several concurrent database connections. For a
long-running production deployment, place RDS Proxy or another compatible
connection pooler in front of RDS and use a least-privilege application
database user instead of the PostgreSQL master user.

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
Lark Base adapter and environment variables are connected. The health endpoint
is `/api/health`.

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

## Lark Base tables

Use stable field names and do not delete or rename fields after integration.

- **Workers:** stable worker key, display name, active status, W-2/1099 type,
  daily rate, and display order.
- **Work Days:** stable day key, linked worker, date, status, total hours,
  start/end time, extra pay, notes, source, and timestamps.
- **Location Entries:** linked work day, location, cost center, time range,
  regular hours, overtime, and display order.
- **Cost Centers:** cost-center ID, name, and active status.
- **Payroll Checks:** worker, period start, checked status, checker, and time.
- **Audit Log:** actor, action, entity key, old/new values, and timestamp.

The browser never calls Lark directly. Vercel functions obtain a tenant token
and perform Base operations server-side. Changes made through the website are
therefore visible in the Base, and edits made in the Base are returned to the
website on refresh. A Base-record-change webhook can invalidate cached data.

## Migration and validation

Do not upload `data/worklog.sqlite3` or payroll workbooks to GitHub. A one-time
server-side migration will read the local SQLite database and batch-create Lark
records after the Base schema is finalized. Validate worker counts, work-day
counts, total hours, pay-period totals, and several individual histories before
switching production to Lark.

Keep a read-only local backup until the Lark totals and exports have been
reconciled. Payroll output is an estimate and should be reviewed against the
company's official workweek, worker classifications, and payroll rules.
