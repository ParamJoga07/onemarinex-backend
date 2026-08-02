#!/usr/bin/env python
"""Check what words are in the database and how they're normalized."""

from app.db.session import SessionLocal
from app.db.models.chat_restricted_word import ChatRestrictedWord
from app.utils.text_normalization import normalize

db = SessionLocal()

# Get all active restricted words
words = db.query(ChatRestrictedWord).filter(ChatRestrictedWord.is_active).all()

print(f"\nTotal active restricted words: {len(words)}\n")

# Check for jagadeesh and raju
target_words = ["jagadeesh", "raju"]

print("=" * 80)
print("CHECKING FOR TARGET WORDS IN DATABASE")
print("=" * 80)

for target in target_words:
    print(f"\nSearching for: {repr(target)}")
    found = False
    for w in words:
        if target.lower() in w.word.lower():
            found = True
            print(f"  Found: word_id={w.id}, word={repr(w.word)}, is_active={w.is_active}")

    if not found:
        print(f"  NOT FOUND in database")

print("\n" + "=" * 80)
print("SHOWING ALL WORDS AND HOW THEY NORMALIZE")
print("=" * 80)

single_words_cache = set()
phrases_cache = []

for w in words:
    stored_word = w.word
    normalized = w.word.lower().strip()

    if ' ' in normalized:
        phrases_cache.append(normalized)
        word_type = "PHRASE"
    else:
        single_words_cache.add(normalized)
        word_type = "SINGLE"

    # Show the first 30 words
    if len(single_words_cache) + len(phrases_cache) <= 30:
        print(f"{word_type:6} | DB: {repr(stored_word):30} | NORMALIZED: {repr(normalized)}")

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
        import re
        clean_token = re.sub(r'[^a-z0-9]', '', token)
        in_dict = clean_token in single_words_cache
        print(f"    Token: {repr(token):20} -> Clean: {repr(clean_token):20} -> In Dict: {in_dict}")

db.close()
