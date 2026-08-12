"""Add historical vessel calls, crew assignments, and event ownership.

Revision ID: l3m4n5o6p7q8
Revises: k2l3m4n5o6p7
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = "l3m4n5o6p7q8"
down_revision = "k2l3m4n5o6p7"
branch_labels = None
depends_on = None


EVENT_COLUMNS = {
    "cab_bookings": (
        ("vessel_call_id", sa.Integer()),
        ("agency_id", sa.Integer()),
        ("port_id", sa.Integer()),
        ("context_resolution", sa.String(32)),
    ),
    "crew_sos_requests": (
        ("vessel_call_id", sa.Integer()),
        ("vessel_id", sa.Integer()),
        ("agency_id", sa.Integer()),
        ("crew_assignment_id", sa.Integer()),
        ("port_id", sa.Integer()),
        ("context_resolution", sa.String(32)),
    ),
    "incidents": (
        ("vessel_call_id", sa.Integer()),
        ("agency_id", sa.Integer()),
        ("crew_profile_id", sa.Integer()),
        ("crew_assignment_id", sa.Integer()),
        ("port_id", sa.Integer()),
        ("context_resolution", sa.String(32)),
    ),
}

FOREIGN_KEYS = (
    ("cab_bookings", "vessel_call_id", "vessel_calls", "SET NULL"),
    ("cab_bookings", "agency_id", "agent_profiles", "SET NULL"),
    ("cab_bookings", "port_id", "ports", "SET NULL"),
    ("crew_sos_requests", "vessel_call_id", "vessel_calls", "RESTRICT"),
    ("crew_sos_requests", "vessel_id", "vessels", "SET NULL"),
    ("crew_sos_requests", "agency_id", "agent_profiles", "SET NULL"),
    ("crew_sos_requests", "crew_assignment_id", "crew_assignments", "SET NULL"),
    ("crew_sos_requests", "port_id", "ports", "SET NULL"),
    ("incidents", "vessel_call_id", "vessel_calls", "RESTRICT"),
    ("incidents", "agency_id", "agent_profiles", "SET NULL"),
    ("incidents", "crew_profile_id", "crew_profiles", "SET NULL"),
    ("incidents", "crew_assignment_id", "crew_assignments", "SET NULL"),
    ("incidents", "port_id", "ports", "SET NULL"),
)


def _inspector():
    return inspect(op.get_bind())


def _tables() -> set[str]:
    return set(_inspector().get_table_names())


def _columns(table: str) -> set[str]:
    inspector = _inspector()
    if table not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def _indexes(table: str) -> set[str]:
    inspector = _inspector()
    if table not in inspector.get_table_names():
        return set()
    return {index["name"] for index in inspector.get_indexes(table)}


def _foreign_key(table: str, column: str):
    inspector = _inspector()
    if table not in inspector.get_table_names():
        return None
    return next(
        (
            foreign_key
            for foreign_key in inspector.get_foreign_keys(table)
            if foreign_key.get("constrained_columns") == [column]
        ),
        None,
    )


def _add_index(table: str, column: str) -> None:
    name = f"ix_{table}_{column}"
    if name not in _indexes(table):
        op.create_index(name, table, [column])


def _add_fk(table: str, column: str, referred_table: str, ondelete: str) -> None:
    if _foreign_key(table, column) is None:
        op.create_foreign_key(
            f"fk_{table}_{column}",
            table,
            referred_table,
            [column],
            ["id"],
            ondelete=ondelete,
        )


def _replace_fk(table: str, column: str, referred_table: str, ondelete: str) -> None:
    foreign_key = _foreign_key(table, column)
    if foreign_key is not None:
        current_delete = str((foreign_key.get("options") or {}).get("ondelete", "")).upper()
        if current_delete == ondelete:
            return
        name = foreign_key.get("name")
        if not name:
            raise RuntimeError(f"Cannot replace unnamed {table}.{column} foreign key")
        op.drop_constraint(name, table, type_="foreignkey")
    op.create_foreign_key(
        f"fk_{table}_{column}",
        table,
        referred_table,
        [column],
        ["id"],
        ondelete=ondelete,
    )


def _create_tables() -> None:
    if "vessel_calls" not in _tables():
        op.create_table(
            "vessel_calls",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("vessel_id", sa.Integer(), nullable=True),
            sa.Column("agency_id", sa.Integer(), nullable=True),
            sa.Column("port_id", sa.Integer(), nullable=True),
            sa.Column("vessel_name", sa.String(255), nullable=False),
            sa.Column("imo_number", sa.String(100), nullable=True),
            sa.Column("flag", sa.String(100), nullable=True),
            sa.Column("agency_name", sa.String(255), nullable=True),
            sa.Column("port_name", sa.String(255), nullable=True),
            sa.Column("eta", sa.DateTime(timezone=True), nullable=True),
            sa.Column("etd", sa.DateTime(timezone=True), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("status", sa.String(32), nullable=False, server_default="ACTIVE"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["vessel_id"], ["vessels.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["agency_id"], ["agent_profiles.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["port_id"], ["ports.id"], ondelete="SET NULL"),
        )
    for column in ("vessel_id", "agency_id", "port_id"):
        _add_index("vessel_calls", column)
    if "uq_vessel_calls_active_vessel" not in _indexes("vessel_calls"):
        op.create_index(
            "uq_vessel_calls_active_vessel",
            "vessel_calls",
            ["vessel_id"],
            unique=True,
            postgresql_where=text("ended_at IS NULL AND vessel_id IS NOT NULL"),
        )

    if "crew_assignments" not in _tables():
        op.create_table(
            "crew_assignments",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("vessel_call_id", sa.Integer(), nullable=False),
            sa.Column("crew_profile_id", sa.Integer(), nullable=True),
            sa.Column("vessel_crew_id", sa.Integer(), nullable=True),
            sa.Column("crew_name", sa.String(255), nullable=False),
            sa.Column("rank", sa.String(100), nullable=True),
            sa.Column("nationality", sa.String(100), nullable=True),
            sa.Column("hpid", sa.String(100), nullable=True),
            sa.Column("passport_number", sa.String(64), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["vessel_call_id"], ["vessel_calls.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["crew_profile_id"], ["crew_profiles.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["vessel_crew_id"], ["vessel_crew.id"], ondelete="SET NULL"),
        )
    for column in ("vessel_call_id", "crew_profile_id", "vessel_crew_id", "hpid"):
        _add_index("crew_assignments", column)
    if "uq_crew_assignments_active_manifest" not in _indexes("crew_assignments"):
        op.create_index(
            "uq_crew_assignments_active_manifest",
            "crew_assignments",
            ["vessel_call_id", "vessel_crew_id"],
            unique=True,
            postgresql_where=text("ended_at IS NULL AND vessel_crew_id IS NOT NULL"),
        )


def _add_event_columns() -> None:
    for table, definitions in EVENT_COLUMNS.items():
        if table not in _tables():
            continue
        existing = _columns(table)
        for column, type_ in definitions:
            if column not in existing:
                op.add_column(table, sa.Column(column, type_, nullable=True))
            _add_index(table, column) if column.endswith("_id") else None
    for table, column, referred_table, ondelete in FOREIGN_KEYS:
        if column in _columns(table):
            _add_fk(table, column, referred_table, ondelete)


def _preserve_crew_owned_records() -> None:
    if "cab_bookings" in _tables() and "crew_id" in _columns("cab_bookings"):
        op.alter_column("cab_bookings", "crew_id", existing_type=sa.Integer(), nullable=True)
        _replace_fk("cab_bookings", "crew_id", "crew_profiles", "SET NULL")
    if "crew_sos_requests" in _tables():
        for column, table in (("user_id", "users"), ("crew_profile_id", "crew_profiles")):
            if column not in _columns("crew_sos_requests"):
                continue
            op.alter_column(
                "crew_sos_requests", column, existing_type=sa.Integer(), nullable=True
            )
            _replace_fk("crew_sos_requests", column, table, "SET NULL")


def _backfill() -> None:
    connection = op.get_bind()
    # One current call per canonical vessel. Snapshots preserve the agency and
    # port values that exist at migration time; later reassignment cannot edit
    # the event's ownership.
    connection.execute(text("""
        INSERT INTO vessel_calls (
            vessel_id, agency_id, port_id, vessel_name, imo_number, flag,
            agency_name, port_name, eta, etd, started_at, ended_at, status
        )
        SELECT
            vessel.id,
            agent.id,
            port.id,
            vessel.name,
            vessel.imo_number,
            vessel.flag,
            COALESCE(agent.agency_name, vessel.agency_name),
            COALESCE(port.code, agent.assigned_port),
            vessel.eta,
            vessel.etd,
            COALESCE(vessel.eta, vessel.created_at, now()),
            CASE
                WHEN upper(COALESCE(vessel.status, 'ACTIVE')) = 'DEPARTED'
                THEN COALESCE(vessel.etd, now())
            END,
            CASE
                WHEN upper(COALESCE(vessel.status, 'ACTIVE')) = 'DEPARTED' THEN 'DEPARTED'
                ELSE 'ACTIVE'
            END
        FROM vessels AS vessel
        LEFT JOIN agent_profiles AS agent ON agent.user_id = vessel.agent_id
        LEFT JOIN ports AS port
          ON port.code = agent.assigned_port OR port.name = agent.assigned_port
        WHERE NOT EXISTS (
            SELECT 1 FROM vessel_calls AS call
            WHERE call.vessel_id = vessel.id
        )
    """))

    # Map a manifest row to a profile only when HPID or passport identifies one
    # unique account. Ambiguous rows remain assignment snapshots with a NULL
    # profile instead of guessing who they represent.
    connection.execute(text("""
        INSERT INTO crew_assignments (
            vessel_call_id, crew_profile_id, vessel_crew_id, crew_name, rank,
            nationality, hpid, passport_number, started_at, ended_at
        )
        SELECT
            call.id,
            CASE WHEN matches.match_count = 1 THEN matches.profile_id END,
            manifest.id,
            manifest.name,
            manifest.rank,
            manifest.nationality,
            manifest.hp_id,
            manifest.passport_number,
            COALESCE(manifest.created_at, call.started_at, now()),
            call.ended_at
        FROM vessel_crew AS manifest
        JOIN vessel_calls AS call
          ON call.vessel_id = manifest.vessel_id
        LEFT JOIN LATERAL (
            SELECT min(profile.id) AS profile_id, count(*) AS match_count
            FROM crew_profiles AS profile
            WHERE (
                NULLIF(trim(manifest.hp_id), '') IS NOT NULL
                AND upper(trim(profile.hpid)) = upper(trim(manifest.hp_id))
            ) OR (
                NULLIF(trim(manifest.passport_number), '') IS NOT NULL
                AND upper(trim(profile.passport_number)) = upper(trim(manifest.passport_number))
            )
        ) AS matches ON true
        WHERE NOT EXISTS (
            SELECT 1 FROM crew_assignments AS assignment
            WHERE assignment.vessel_call_id = call.id
              AND assignment.vessel_crew_id = manifest.id
              AND assignment.ended_at IS NULL
        )
    """))

    connection.execute(text("""
        UPDATE cab_bookings AS booking
        SET vessel_call_id = call.id,
            agency_id = call.agency_id,
            port_id = call.port_id,
            context_resolution = 'vessel_id'
        FROM vessel_calls AS call
        WHERE booking.vessel_call_id IS NULL
          AND booking.vessel_id = call.vessel_id
    """))
    # SOS backfill priority: linked booking, exact stored vessel name, otherwise
    # unresolved. The stored vessel name is an event-time snapshot and is safer
    # than asking where the crew member is assigned today.
    connection.execute(text("""
        UPDATE crew_sos_requests AS sos
        SET vessel_call_id = booking.vessel_call_id,
            vessel_id = booking.vessel_id,
            agency_id = booking.agency_id,
            port_id = booking.port_id,
            context_resolution = 'booking'
        FROM cab_bookings AS booking
        WHERE sos.vessel_call_id IS NULL
          AND sos.cab_booking_id = booking.id
          AND booking.vessel_call_id IS NOT NULL
    """))
    connection.execute(text("""
        UPDATE crew_sos_requests AS sos
        SET vessel_call_id = resolved.call_id,
            vessel_id = resolved.vessel_id,
            agency_id = resolved.agency_id,
            port_id = resolved.port_id,
            context_resolution = 'vessel_name'
        FROM (
            SELECT names.vessel_name,
                   min(c.id) AS call_id,
                   min(c.vessel_id) AS vessel_id,
                   min(c.agency_id) AS agency_id,
                   min(c.port_id) AS port_id
            FROM (
                SELECT DISTINCT lower(trim(vessel)) AS vessel_name
                FROM crew_sos_requests
                WHERE NULLIF(trim(vessel), '') IS NOT NULL
            ) AS names
            JOIN vessel_calls AS c ON lower(trim(c.vessel_name)) = names.vessel_name
            GROUP BY names.vessel_name
            HAVING count(c.id) = 1
        ) AS resolved
        WHERE sos.vessel_call_id IS NULL
          AND lower(trim(sos.vessel)) = resolved.vessel_name
    """))
    connection.execute(text("""
        UPDATE crew_sos_requests AS sos
        SET crew_assignment_id = resolved.assignment_id
        FROM (
            SELECT vessel_call_id, crew_profile_id, min(id) AS assignment_id
            FROM crew_assignments
            WHERE crew_profile_id IS NOT NULL
            GROUP BY vessel_call_id, crew_profile_id
            HAVING count(*) = 1
        ) AS resolved
        WHERE sos.crew_assignment_id IS NULL
          AND sos.vessel_call_id = resolved.vessel_call_id
          AND sos.crew_profile_id = resolved.crew_profile_id
    """))
    connection.execute(text("""
        UPDATE crew_sos_requests
        SET context_resolution = 'unresolved'
        WHERE context_resolution IS NULL
    """))

    # Incidents already carry a strong vessel_id in the newer data. Prefer a
    # selected trip when present, then that stored foreign key. Never resolve a
    # historical incident through the reporter's current manifest.
    connection.execute(text("""
        UPDATE incidents AS incident
        SET vessel_call_id = booking.vessel_call_id,
            vessel_id = COALESCE(incident.vessel_id, booking.vessel_id),
            agency_id = booking.agency_id,
            port_id = booking.port_id,
            context_resolution = 'booking'
        FROM cab_bookings AS booking
        WHERE incident.vessel_call_id IS NULL
          AND incident.trip_id = booking.booking_id
          AND booking.vessel_call_id IS NOT NULL
    """))
    connection.execute(text("""
        UPDATE incidents AS incident
        SET vessel_call_id = call.id,
            agency_id = call.agency_id,
            port_id = call.port_id,
            context_resolution = 'vessel_id'
        FROM vessel_calls AS call
        WHERE incident.vessel_call_id IS NULL
          AND incident.vessel_id = call.vessel_id
    """))
    connection.execute(text("""
        UPDATE incidents AS incident
        SET crew_profile_id = resolved.profile_id
        FROM (
            SELECT identifiers.reporter_id,
                   min(p.id) AS profile_id
            FROM (
                SELECT DISTINCT lower(trim(reporter_id)) AS reporter_id
                FROM incidents
                WHERE NULLIF(trim(reporter_id), '') IS NOT NULL
            ) AS identifiers
            JOIN crew_profiles AS p
              ON lower(trim(p.hpid)) = identifiers.reporter_id
            GROUP BY identifiers.reporter_id
            HAVING count(p.id) = 1
        ) AS resolved
        WHERE incident.crew_profile_id IS NULL
          AND lower(trim(incident.reporter_id)) = resolved.reporter_id
    """))
    connection.execute(text("""
        UPDATE incidents AS incident
        SET crew_assignment_id = resolved.assignment_id
        FROM (
            SELECT vessel_call_id, crew_profile_id, min(id) AS assignment_id
            FROM crew_assignments
            WHERE crew_profile_id IS NOT NULL
            GROUP BY vessel_call_id, crew_profile_id
            HAVING count(*) = 1
        ) AS resolved
        WHERE incident.crew_assignment_id IS NULL
          AND incident.vessel_call_id = resolved.vessel_call_id
          AND incident.crew_profile_id = resolved.crew_profile_id
    """))
    connection.execute(text("""
        UPDATE incidents
        SET context_resolution = 'unresolved'
        WHERE context_resolution IS NULL
    """))


def upgrade() -> None:
    _create_tables()
    _add_event_columns()
    _preserve_crew_owned_records()
    _backfill()


def downgrade() -> None:
    # Release 1 preserves history. Destructive downgrade is deliberately
    # unsupported; roll application code back while retaining additive schema.
    raise RuntimeError("Release 1 historical context cannot be safely downgraded")
