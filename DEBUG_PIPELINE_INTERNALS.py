#!/usr/bin/env python
"""Trace the actual _get_cached_dictionary and _check_dictionary functions."""

import re
from typing import Set, Optional
from app.db.session import SessionLocal
from sqlalchemy.orm import Session
from sqlalchemy import text

# Import the actual functions
from app.services.chat_moderation import _get_cached_dictionary, _check_dictionary
from app.utils.text_normalization import normalize

print("=" * 80)
print("DEBUGGING: _get_cached_dictionary and _check_dictionary")
print("=" * 80)

test_messages = [
    "modi is idiot",
    "all indians are idiots",
    "pakistanis are dumb ass",
    "DRUGS ARE INJURIOUS",
]

db = SessionLocal()

for raw_message in test_messages:
    print(f"\n{'=' * 80}")
    print(f"TESTING: '{raw_message}'")
    print(f"{'=' * 80}")

    normalized = normalize(raw_message)
    print(f"\n1. Input")
    print(f"   Raw:        '{raw_message}'")
    print(f"   Normalized: '{normalized}'")

    # Call the actual function
    print(f"\n2. CALLING _get_cached_dictionary")
    single_words, phrase_regex = _get_cached_dictionary(db)
    print(f"   single_words count: {len(single_words) if single_words else 0}")
    print(f"   phrase_regex exists: {phrase_regex is not None}")

    # Check if dictionary is empty
    if not single_words:
        print(f"\n   !!! WARNING: single_words is EMPTY !!!")
    else:
        print(f"   Sample words in dictionary: {list(single_words)[:10]}")

    # Call _check_dictionary
    print(f"\n3. CALLING _check_dictionary")
    matched_term = _check_dictionary(normalized, single_words, phrase_regex)
    print(f"   Result: matched_term = {matched_term}")

    # Debug: manually check what _check_dictionary is doing
    print(f"\n4. MANUAL VERIFICATION (what _check_dictionary should do)")
    tokens = normalized.split()
    print(f"   Tokens: {tokens}")

    for token in tokens:
        clean_token = re.sub(r'[^a-z0-9]', '', token)
        in_dict = clean_token in single_words if single_words else False
        print(f"     '{token}' -> '{clean_token}': {in_dict}")

db.close()

print(f"\n{'=' * 80}")
print("END DEBUG")
print(f"{'=' * 80}")
