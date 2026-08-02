#!/usr/bin/env python
"""Direct trace of moderation function with minimal imports."""

import sys
import asyncio
from datetime import datetime

# Minimal imports to avoid circular dependencies
from app.db.session import SessionLocal
from sqlalchemy import text

print("=" * 80)
print("DIRECT RUNTIME TRACE TEST")
print("=" * 80)

# Open database connection
db = SessionLocal()

# Test 1: Verify dictionary loading
print("\nTEST 1: Check dictionary in database")
print("-" * 80)

with db.bind.connect() as conn:
    result = conn.execute(text("""
        SELECT word FROM chat_restricted_words
        WHERE word IN ('idiot', 'idiots', 'drugs', 'porn', 'dumb', 'ass')
        AND is_active = true
    """))
    found = {row[0] for row in result.fetchall()}
    print(f"Found in database: {found}")
    print(f"Total found: {len(found)}")

# Test 2: Check moderation cache state
print("\nTEST 2: Check module-level cache")
print("-" * 80)

# Import the module and check the globals
import app.services.chat_moderation as mod

print(f"_dictionary_cache: {mod._dictionary_cache}")
print(f"_cache_loaded_at: {mod._cache_loaded_at}")
print(f"_phrase_regex: {mod._phrase_regex}")

# Test 3: Call _get_cached_dictionary to force load
print("\nTEST 3: Call _get_cached_dictionary()")
print("-" * 80)

single_words, phrase_regex = mod._get_cached_dictionary(db)
print(f"Returned single_words size: {len(single_words)}")
print(f"Returned phrase_regex: {phrase_regex is not None}")
print(f"Sample words: {list(single_words)[:10]}")

# Test 4: Check if our test words are in the returned set
print("\nTEST 4: Check returned dictionary for test words")
print("-" * 80)

test_words = ['idiot', 'idiots', 'drugs', 'porn', 'dumb', 'ass']
for word in test_words:
    in_dict = word in single_words
    print(f"  '{word}' in dictionary: {in_dict}")

# Test 5: Call _check_dictionary directly
print("\nTEST 5: Test _check_dictionary directly")
print("-" * 80)

test_cases = [
    "modi is idiot",
    "all indians are idiots",
    "DRUGS ARE INJURIOUS",
]

from app.utils.text_normalization import normalize

for msg in test_cases:
    normalized = normalize(msg)
    result = mod._check_dictionary(normalized, single_words, phrase_regex)
    print(f"\n  Message: '{msg}'")
    print(f"  Normalized: '{normalized}'")
    print(f"  Tokens: {normalized.split()}")
    print(f"  Match result: {result}")

db.close()

print(f"\n{'=' * 80}")
print("END TRACE TEST")
print(f"{'=' * 80}")
