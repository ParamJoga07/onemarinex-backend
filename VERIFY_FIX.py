#!/usr/bin/env python
"""Verify that the cache fix works by checking recent moderation events."""

from app.db.session import engine
from sqlalchemy import text
from datetime import datetime, timedelta

print("=" * 80)
print("VERIFYING CACHE FIX")
print("=" * 80)

# First, clear old test data or skip if too many rows
with engine.connect() as conn:
    # Get count
    result = conn.execute(text("SELECT COUNT(*) FROM chat_moderation_events"))
    count = result.scalar()
    print(f"\nTotal moderation events in database: {count}")

print("\nChecking recent events (last 5):")
print("-" * 80)

with engine.connect() as conn:
    result = conn.execute(text("""
        SELECT
            id,
            raw_message,
            decision,
            matched_term,
            reason_code,
            rejected_by,
            created_at
        FROM chat_moderation_events
        ORDER BY created_at DESC
        LIMIT 5
    """))

    for row in result.fetchall():
        msg_id, msg, decision, term, reason, rejected, created = row
        print(f"\nID: {msg_id}")
        print(f"  Message: '{msg}'")
        print(f"  Decision: {decision}")
        print(f"  Matched Term: {term}")
        print(f"  Reason: {reason}")
        print(f"  Rejected By: {rejected}")
        print(f"  Time: {created}")

print(f"\n{'=' * 80}")
print("EXPECTED AFTER FIX:")
print("=" * 80)
print("""
Messages that should NOW be REJECTED:
  - 'modi is idiot' → matched_term: idiot, reason: guidelines_violation
  - 'all indians are idiots' → matched_term: idiots, reason: guidelines_violation
  - 'DRUGS ARE INJURIOUS' → matched_term: drugs, reason: guidelines_violation
  - 'pakistanis are dumb ass' → matched_term: dumb/ass, reason: guidelines_violation

Messages that should be ALLOWED:
  - 'I want to go to Italian restaurant' → No match, backend
  - 'is indian food available' → No match, backend
""")
