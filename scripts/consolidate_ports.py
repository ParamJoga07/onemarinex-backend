#!/usr/bin/env python3
"""Plan or execute a transactional canonical-port merge.

Usage (dry run): python scripts/consolidate_ports.py SOURCE_ID TARGET_ID
Apply: python scripts/consolidate_ports.py SOURCE_ID TARGET_ID --apply

The target survives. Every actual FK to ports is discovered from the database,
all exact string port references are repointed, compatible PortRule values are
merged, and the source is deleted in one transaction. Any unique-key conflict
rolls the entire operation back instead of leaving a partial merge.
"""

import argparse
import os
import sys
from sqlalchemy import inspect, text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.base import Base  # noqa: F401
from app.db.session import SessionLocal
from app.db.models.port import Port
from app.db.models.port_rule import PortRule


STRING_COLUMNS = ("port_name", "current_port", "assigned_port")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source_id", type=int)
    parser.add_argument("target_id", type=int)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.source_id == args.target_id:
        parser.error("source and target must differ")
    db = SessionLocal()
    try:
        source, target = db.get(Port, args.source_id), db.get(Port, args.target_id)
        if not source or not target:
            raise SystemExit("Source or target port was not found")
        bind = db.get_bind()
        inspector = inspect(bind)
        plan = []
        for table in inspector.get_table_names():
            columns = {column["name"] for column in inspector.get_columns(table)}
            for fk in inspector.get_foreign_keys(table):
                if fk.get("referred_table") == "ports":
                    column = fk["constrained_columns"][0]
                    count = db.execute(text(f'SELECT count(*) FROM "{table}" WHERE "{column}"=:source'), {"source": source.id}).scalar()
                    if count:
                        plan.append((table, column, count, "foreign key"))
                        if args.apply:
                            db.execute(text(f'UPDATE "{table}" SET "{column}"=:target WHERE "{column}"=:source'), {"target": target.id, "source": source.id})
            for column in STRING_COLUMNS:
                if column not in columns or table == "port_rules":
                    continue
                count = db.execute(text(f'SELECT count(*) FROM "{table}" WHERE "{column}" IN (:code,:name)'), {"code": source.code, "name": source.name}).scalar()
                if count:
                    plan.append((table, column, count, "string reference"))
                    if args.apply:
                        db.execute(text(f'UPDATE "{table}" SET "{column}"=:target WHERE "{column}" IN (:code,:name)'), {"target": target.code, "code": source.code, "name": source.name})

        source_rule = db.query(PortRule).filter(PortRule.port_name.in_([source.code, source.name])).first()
        target_rule = db.query(PortRule).filter(PortRule.port_name.in_([target.code, target.name])).first()
        if source_rule:
            plan.append(("port_rules", "port_name", 1, "merge"))
            if args.apply:
                if target_rule:
                    for field in ("rules", "opening_time", "closing_time", "timezone", "working_days", "advance_booking_buffer_minutes", "contact_email", "helpline_number"):
                        if getattr(target_rule, field, None) in (None, "", []):
                            setattr(target_rule, field, getattr(source_rule, field, None))
                    db.delete(source_rule)
                else:
                    source_rule.port_name = target.code

        print(f"Merge {source.id} {source.name!r} -> {target.id} {target.name!r}")
        for item in plan:
            print(f"  {item[2]} {item[3]} row(s): {item[0]}.{item[1]}")
        if args.apply:
            db.delete(source)
            db.commit()
            print("COMMITTED")
        else:
            db.rollback()
            print("DRY RUN ONLY — rerun with --apply after reviewing the plan")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
