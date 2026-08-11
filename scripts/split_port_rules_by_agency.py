"""Move agency-specific rules off the shared port row and onto their agency.

Agents used to edit `port_rules.rules`, which holds one row per port shared by
every agency berthed there. Rules now live on `agent_profiles.agency_rules` and
reach only that agent's vessels — but rules written *before* that split are
still sitting on the port row, showing to everyone.

Nothing can tell from the data who wrote a given rule, so this does not guess.
It shows you what is there and who is berthed at each port, then moves a rule
you name to an agency you name.

Usage (from onemarinex-backend/):

    # 1. See what each port holds and which agencies are berthed there
    PYTHONPATH=. python scripts/split_port_rules_by_agency.py

    # 2. Move rule #0 at that port to one agency (dry run first)
    PYTHONPATH=. python scripts/split_port_rules_by_agency.py \\
        --port port_visakhapatnam --rule 0 --to agent@example.com

    # 3. Same command with --apply to write it
    PYTHONPATH=. python scripts/split_port_rules_by_agency.py \\
        --port port_visakhapatnam --rule 0 --to agent@example.com --apply

`--to` may be repeated to give the same rule to several agencies, which is what
you want when two agencies had both been relying on it.

By default the rule is *copied* to the agency and left on the port. Add
`--remove-from-port` once every agency that needs it has a copy; leaving it in
both places is safe but shows crew the same rule twice.
"""
import argparse
import json
import sys

import app.db.base  # noqa: F401 — registers every model on Base
from app.db.session import SessionLocal
from app.db.models.agent_profile import AgentProfile
from app.db.models.port_rule import PortRule
from app.db.models.user import User
from app.db.models.vessel import Vessel


def _as_list(value):
    if not value:
        return []
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return []
        return parsed if isinstance(parsed, list) else []
    return list(value) if isinstance(value, list) else []


def report(db) -> int:
    rows = db.query(PortRule).order_by(PortRule.port_name).all()
    if not rows:
        print("No port rules configured.")
        return 0

    for row in rows:
        rules = _as_list(row.rules)
        print(f"\n=== {row.port_name} — {len(rules)} rule(s) on the shared port row ===")
        for index, rule in enumerate(rules):
            title = (rule or {}).get("title", "(untitled)")
            description = (rule or {}).get("description", "")
            print(f"  [{index}] {title}")
            if description:
                print(f"       {description[:96]}")

        agencies = (
            db.query(AgentProfile, User.email)
            .join(User, User.id == AgentProfile.user_id)
            .filter(AgentProfile.assigned_port == row.port_name)
            .all()
        )
        if not agencies:
            print("  agencies berthed here: none — nothing to split, leave as port-wide")
            continue
        print("  agencies berthed here:")
        for profile, email in agencies:
            owned = db.query(Vessel).filter(Vessel.agent_id == profile.user_id).count()
            existing = len(_as_list(profile.agency_rules))
            print(f"    - {profile.agency_name} <{email}>  "
                  f"{owned} vessel(s), {existing} own rule(s)")

    print("\nA rule only needs moving if an agent wrote it for their own crew.")
    print("Anything the superadmin set for the whole port should stay where it is.")
    return 0


def move(db, port_name, rule_index, emails, remove_from_port, apply) -> int:
    port_row = db.query(PortRule).filter(PortRule.port_name == port_name).first()
    if not port_row:
        print(f"No port rules row for {port_name!r}. Run without arguments to list ports.")
        return 1

    rules = _as_list(port_row.rules)
    if rule_index < 0 or rule_index >= len(rules):
        print(f"{port_name} has {len(rules)} rule(s); --rule {rule_index} is out of range.")
        return 1
    rule = rules[rule_index]
    print(f"Rule [{rule_index}] on {port_name}: {rule.get('title', '(untitled)')!r}")

    targets = []
    for email in emails:
        profile = (
            db.query(AgentProfile)
            .join(User, User.id == AgentProfile.user_id)
            .filter(User.email == email)
            .first()
        )
        if not profile:
            print(f"  no agency profile for {email!r}")
            return 1
        targets.append((email, profile))

    for email, profile in targets:
        existing = _as_list(profile.agency_rules)
        already = any(
            (item or {}).get("title") == rule.get("title") for item in existing
        )
        if already:
            print(f"  {profile.agency_name} <{email}> already has a rule with that title — skipping")
            continue
        print(f"  -> copy to {profile.agency_name} <{email}> "
              f"({len(existing)} -> {len(existing) + 1} rule(s))")
        if apply:
            # Reassign rather than mutate: SQLAlchemy does not track in-place
            # edits to a JSON column, so appending would not be persisted.
            profile.agency_rules = existing + [rule]

    if remove_from_port:
        print(f"  -> remove from the {port_name} port row "
              f"({len(rules)} -> {len(rules) - 1} rule(s))")
        if apply:
            port_row.rules = [r for i, r in enumerate(rules) if i != rule_index]
    else:
        print("  -> leaving it on the port row "
              "(pass --remove-from-port once every agency that needs it has a copy)")

    if not apply:
        print("\nDry run. Re-run with --apply to write these changes.")
        return 0

    db.commit()
    print("\nDone.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Move agency-specific rules off the shared port row.")
    parser.add_argument("--port", help="port_name as shown in the report")
    parser.add_argument("--rule", type=int, help="index of the rule, from the report")
    parser.add_argument("--to", action="append", default=[], metavar="EMAIL",
                        help="agent email to copy the rule to; repeatable")
    parser.add_argument("--remove-from-port", action="store_true",
                        help="also drop the rule from the shared port row")
    parser.add_argument("--apply", action="store_true",
                        help="actually write; otherwise report what would change")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.port is None and args.rule is None and not args.to:
            return report(db)
        if args.port is None or args.rule is None or not args.to:
            parser.error("--port, --rule and at least one --to are required together")
        return move(db, args.port, args.rule, args.to,
                    args.remove_from_port, args.apply)
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
