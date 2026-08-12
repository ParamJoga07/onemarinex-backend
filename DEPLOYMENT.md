# Deployment: how schema changes reach production

## The short version

Two mechanisms, deliberately overlapping:

1. **Alembic migrations** — canonical. Applied by `python -m app.db.migrate`.
2. **`ensure_*` guards in `app/main.py`** — a safety net that runs on every boot
   and applies the same DDL with `ADD COLUMN IF NOT EXISTS`.

The guards exist because this app has historically deployed with no pre-deploy
hook, so migrations never ran. Every recent schema change therefore shipped
twice: once as a migration, once as a guard. If you add a migration that alters
an existing table, **add a matching guard**, or the change will not reach
production until someone runs the migration by hand.

New *tables* need no guard: `Base.metadata.create_all()` runs at startup and
creates any table that is missing. It never `ALTER`s one that exists, which is
why columns need the guards.

## Running migrations

```bash
python -m app.db.migrate
```

**Not** `alembic upgrade head`. This project's history cannot be replayed from
base — the earliest revision alters `rfqs` / `rfq_quotes`, tables from a retired
product, and dies with `UndefinedTable` against an empty database. `app.db.migrate`
handles the baseline-then-delta path and takes a Postgres advisory lock so two
instances starting together serialise instead of racing on DDL.

## Release 0: repair the duplicate migration graph

Production was stamped at `i0k1l2m3n4o5`, but two newer migrations reused the
already-deployed revision IDs `a2c3d4e5f6g7` and `b3d4e5f6g7h8`. Release 0
reissues only those newer changes as one linear, additive chain:

```text
i0k1l2m3n4o5
  -> j1k2l3m4n5o6  cab_bookings.vessel_id
  -> k2l3m4n5o6p7  agent_profiles.agency_rules
```

After deploying the Release 0 code, run these commands in the backend console:

```bash
PYTHONPATH=. python scripts/preflight_release_zero.py
python -m app.db.migrate
python -m alembic current
python -m alembic heads
```

Do not run the migration if preflight reports orphaned
`cab_bookings.vessel_id` values. Reconcile those bookings first. A successful
deployment ends with both `current` and `heads` reporting only:

```text
k2l3m4n5o6p7 (head)
```

This release repairs the migration foundation only. Historical vessel-call and
crew-assignment tables, event backfills, archival lifecycle changes, and report
snapshots belong in subsequent releases.

## Release 1: immutable vessel and crew history

Release 1 starts only from the verified Release 0 head and adds a linear chain:

```text
k2l3m4n5o6p7
  -> l3m4n5o6p7q8  vessel calls, crew assignments, event ownership, safe deletes
  -> m4n5o6p7q8r9  booking-to-crew-assignment link
```

The migrations are additive. They preserve SOS, Incident, and booking rows when
a crew profile or vessel is removed, and backfill context only from evidence
stored on the event: linked booking first, then a unique stored vessel. They do
not assign unresolved or ambiguous events through the crew member's current
manifest.

After deploying the Release 1 backend code, run in the backend console:

```bash
python -m alembic current
python -m alembic heads
PYTHONPATH=. python scripts/preflight_release_one.py
python -m app.db.migrate
echo "migration_exit=$?"
python -m alembic current
python -m alembic heads
PYTHONPATH=. python scripts/preflight_release_one.py
```

Before migration, `current` must be `k2l3m4n5o6p7 (head)` and `heads` must show
only `m4n5o6p7q8r9 (head)`. Do not continue if preflight prints `BLOCKED`.
After migration, both `current` and `heads` must show only:

```text
m4n5o6p7q8r9 (head)
```

The post-migration preflight prints resolved and unresolved context counts.
Unresolved historical rows are intentionally retained for manual reconciliation
and are not exposed to an agent by current-crew inference. Never "repair" them
by assigning the crew member's present vessel. Release 1 has no destructive
downgrade; roll the application back while leaving this additive schema intact.

## Before the first run, check the stamp

```sql
SELECT version_num FROM alembic_version;
```

| Result | What it means | What to do |
|---|---|---|
| table missing / empty | never stamped | **Stamp at the revision matching your current schema first**, then upgrade. Running `app.db.migrate` while unstamped will `create_all()` + stamp head and apply **no deltas**, leaving new columns missing on a database marked up to date. |
| the current head | already up to date | nothing |
| an older revision | deltas pending | upgrade, but expect migrations whose work a guard already did. All revisions from `w1c2d3e4f5g6` onward are idempotent; older ones may not be. |

To stamp without running DDL:

```bash
alembic stamp <revision>
```

## Adding a pre-deploy job (DigitalOcean App Platform)

A **Pre-Deploy Job** runs after build and before the new version takes traffic.
If it fails, the deployment is aborted and the previous version keeps serving —
which is exactly the behaviour you want from a migration step.

Dashboard: **App → Create Component → Job**, Job Type **Pre-Deploy**, same repo
and branch as the web service, run command `python -m app.db.migrate`. It must
receive the **same `DATABASE_URL`** as the web component.

As spec YAML:

```yaml
jobs:
  - name: migrate
    kind: PRE_DEPLOY
    run_command: python -m app.db.migrate
    environment_slug: python
    instance_count: 1
    instance_size_slug: apps-s-1vcpu-0.5gb
    github:
      repo: onemarinex/onemarinex-backend
      branch: main
    envs:
      - key: DATABASE_URL
        scope: RUN_TIME
        value: ${db.DATABASE_URL}
```

> **Do not apply this fragment on its own.** `doctl apps update --spec` replaces
> the entire app spec, so a file containing only this block would delete the web
> service. Export the current spec first, merge this in, then apply:
>
> ```bash
> doctl apps spec get <app-id> > app.yaml
> # merge the jobs: block into app.yaml
> doctl apps update <app-id> --spec app.yaml
> ```

## Migrations must be backward compatible

A pre-deploy job runs while the **old** code is still serving. Until the new
version takes over, the previous release is querying the migrated schema. So a
migration may add nullable columns, add tables, and add enum values; it must not
drop or rename anything, or add a `NOT NULL` column without a default, until the
release *after* the one that stopped using it.

## Note on `procfile`

The file is committed lowercase, so buildpacks looking for `Procfile` ignore it
and the start command comes from the platform dashboard instead. Renaming it
would silently change how the app starts if the dashboard command differs —
check that the dashboard says
`uvicorn app.main:app --host 0.0.0.0 --port $PORT` before renaming.
