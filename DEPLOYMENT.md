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
