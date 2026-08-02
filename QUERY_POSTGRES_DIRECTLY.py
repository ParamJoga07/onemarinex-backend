#!/usr/bin/env python
"""Query the PostgreSQL database directly."""

import re
from sqlalchemy import create_engine, text
from app.utils.text_normalization import normalize

# PostgreSQL connection
DATABASE_URL = "postgresql+psycopg2://onemarinex_user:onemarinex123!@localhost:5432/onemarinex"

engine = create_engine(DATABASE_URL)

with engine.connect() as conn:
    # Get all active restricted words
    query = "SELECT id, word, is_active FROM chat_restricted_word WHERE is_active = TRUE"
    result = conn.execute(text(query))
    all_words = result.fetchall()

    print(f"\nTotal active restricted words: {len(all_words)}\n")

    # Check for jagadeesh and raju
    target_words = ["jagadeesh", "raju"]

    print("=" * 80)
    print("CHECKING FOR TARGET WORDS IN DATABASE")
    print("=" * 80)

    for target in target_words:
        print(f"\nSearching for: {repr(target)}")
        found = False
        for word_id, word, is_active in all_words:
            if target.lower() in word.lower():
                found = True
                print(f"  Found: id={word_id}, word={repr(word)}, is_active={is_active}")

        if not found:
            print(f"  NOT FOUND in database")

    print("\n" + "=" * 80)
    print("SIMULATING CACHE LOADING (first 50 words)")
    print("=" * 80)

    single_words_cache = set()
    phrases_cache = []

    for word_id, word, is_active in all_words:
        stored_word = word
        normalized_word = word.lower().strip()

        if ' ' in normalized_word:
            phrases_cache.append(normalized_word)
            word_type = "PHRASE"
        else:
            single_words_cache.add(normalized_word)
            word_type = "SINGLE"

        # Show first 50 entries
        if len(single_words_cache) + len(phrases_cache) <= 50:
            print(f"{word_type:6} | DB: {repr(stored_word):30} | NORMALIZED: {repr(normalized_word)}")

    print(f"\n{'='*80}")
    print(f"CACHE SUMMARY:")
    print(f"  Single words in cache: {len(single_words_cache)}")
    print(f"  Phrases in cache: {len(phrases_cache)}")

    # Check if target words are in the cache
    print(f"\n{'='*80}")
    print("CHECKING TARGET WORDS IN CACHE:")
    print(f"{'='*80}")

    for target in target_words:
        in_cache = target in single_words_cache
        print(f"  {repr(target):20} in single_words_cache: {in_cache}")

    # Now test normalization of incoming messages
    print(f"\n{'='*80}")
    print("TESTING MESSAGE NORMALIZATION AND TOKENIZATION:")
    print(f"{'='*80}")

    test_messages = [
        "jagadeesh",
        "jagadeesh is good",
        "hello jagadeesh",
        "raju",
        "raju is good",
    ]

    for msg in test_messages:
        normalized = normalize(msg)
        tokens = normalized.split()
        print(f"\nMessage: {repr(msg)}")
        print(f"  Normalized: {repr(normalized)}")
        print(f"  Tokens: {tokens}")

        for token in tokens:
            clean_token = re.sub(r'[^a-z0-9]', '', token)
            in_dict = clean_token in single_words_cache
            print(f"    Token: {repr(token):20} -> Clean: {repr(clean_token):20} -> In Dict: {in_dict}")

print(f"\n{'='*80}")
