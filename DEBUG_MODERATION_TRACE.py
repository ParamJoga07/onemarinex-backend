#!/usr/bin/env python
"""Debug trace of moderation pipeline for specific failing messages.

This script traces messages through the ACTUAL pipeline with detailed logging
to identify where dictionary matches are being lost or overridden.
"""

import re
from typing import Set, Optional
from app.db.session import engine, SessionLocal
from sqlalchemy import text
from app.utils.text_normalization import normalize

print("=" * 80)
print("DETAILED MODERATION PIPELINE TRACE")
print("=" * 80)

# Load the actual restricted words dictionary
print("\n1. LOADING RESTRICTED WORDS FROM DATABASE")
print("-" * 80)

db = SessionLocal()
with engine.connect() as conn:
    result = conn.execute(text("SELECT word FROM chat_restricted_words WHERE is_active = true"))
    restricted_words = {row[0] for row in result.fetchall()}

print(f"Total restricted words loaded: {len(restricted_words)}")
print(f"\nChecking for 'idiot' variants:")
for word in sorted(restricted_words):
    if 'idiot' in word.lower():
        print(f"  [FOUND] '{word}'")

# Test cases
test_messages = [
    "modi is idiot",
    "all indians are idiots",
    "black people are idiots",
    "pakistanis are dumb ass",
    "DRUGS ARE INJURIOUS",
]

for raw_message in test_messages:
    print(f"\n{'=' * 80}")
    print(f"TESTING: '{raw_message}'")
    print(f"{'=' * 80}")

    # Step 1: Normalization
    normalized = normalize(raw_message)
    print(f"\n1. NORMALIZATION")
    print(f"   Raw:        '{raw_message}'")
    print(f"   Normalized: '{normalized}'")

    # Step 2: Tokenization
    tokens = normalized.split()
    print(f"\n2. TOKENIZATION")
    print(f"   Tokens: {tokens}")

    # Step 3: Dictionary lookup - detailed
    print(f"\n3. DICTIONARY LOOKUP (DETAILED)")
    print(f"   Checking each token:")

    matched_term = None
    for token in tokens:
        clean_token = re.sub(r'[^a-z0-9]', '', token)
        in_dict = clean_token in restricted_words

        status = "MATCH" if in_dict else "no match"
        print(f"     Token: '{token:20}' -> Clean: '{clean_token:20}' [{status}]")

        if in_dict and not matched_term:
            matched_term = clean_token
            print(f"       >>> DICTIONARY MATCH FOUND: '{matched_term}'")

    print(f"\n   Final matched_term: {matched_term}")

    # Step 4: Check what database shows
    print(f"\n4. DATABASE VERIFICATION")
    with engine.connect() as conn:
        for term in set(tokens):
            clean = re.sub(r'[^a-z0-9]', '', term.lower())
            result = conn.execute(
                text("SELECT word FROM chat_restricted_words WHERE word = :w AND is_active = true"),
                {"w": clean}
            )
            found = result.fetchone()
            print(f"   '{clean}' in database: {bool(found)}")

    # Step 5: Check recent moderation event
    print(f"\n5. CHECK DATABASE FOR THIS MESSAGE")
    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT decision, matched_term, reason_code, rejected_by, moderation_layer
                FROM chat_moderation_events
                WHERE raw_message = :msg
                ORDER BY created_at DESC
                LIMIT 1
            """),
            {"msg": raw_message}
        )
        row = result.fetchone()
        if row:
            print(f"   Decision: {row[0]}")
            print(f"   Matched Term: {row[1]}")
            print(f"   Reason Code: {row[2]}")
            print(f"   Rejected By: {row[3]}")
            print(f"   Moderation Layer: {row[4]}")
        else:
            print(f"   No moderation event found in database")

db.close()

print(f"\n{'=' * 80}")
print("END TRACE")
print(f"{'=' * 80}")
