# Online deployment and data storage

The two web experiences should be published as separate URLs while sharing one
API and one database:

- `check.example.com` — read-focused checking, payroll, and location reports.
- `log.example.com` — mobile-first foreman logging.
- `api.example.com` — authenticated server used by both sites.

Locally, the same separation is available at `localhost:8000` for checking and
`localhost:7001` for logging. Both ports use the same API code and SQLite file.

## Production storage

Use a managed PostgreSQL database for workers, work days, locations, connected
cost centers, payroll checks, preferences, and the audit log. SQLite remains a
good local-development database, but a single SQLite file should not be shared
directly by several web-server instances or downloaded to phones.

Store uploaded and generated Excel workbooks in private object storage, not in
the database. The database should keep only the object key, filename, checksum,
uploader, and timestamps. Provide downloads through short-lived signed URLs.

Browser local storage should contain only temporary unsaved drafts and cached
suggestions. The server database is the source of truth. A successful save must
finish on the server before the UI says the entry is saved.

## Accounts and permissions

- **Foreman:** create and edit daily logs for permitted crews/dates.
- **Checker/payroll:** read reports and mark payroll periods checked.
- **Administrator:** manage workers, cost centers, imports, exports, and roles.

Every production API route should require an account. Use secure cookies,
HTTPS, server-side authorization on every request, rate limits, and a short
session lifetime on shared phones. Keep the Gemini key and database credentials
only in server environment secrets.

## Reliability

- Enable automated daily database backups and point-in-time recovery.
- Keep the audit log for every create/update, including user ID and timestamp.
- Use database transactions when saving a day, its locations, and their cost
  centers so partial records cannot be created.
- Add a unique constraint for one worker and date, as the local schema already
  does.
- Encrypt database and object storage at rest and use TLS in transit.
- Test restoration from backup before inviting foremen to use the system.

## Suggested migration path

1. Add authentication and roles.
2. Move the SQLite schema and current data into PostgreSQL.
3. Move workbook files into private object storage.
4. Deploy the API, checking site, and logging site.
5. Run a short pilot with one foreman and compare its payroll output against the
   current workbook before company-wide use.
