#!/usr/bin/env python
"""Query the database directly without importing models."""

import sqlite3
import re
from app.utils.text_normalization import normalize

# Try both database files
db_files = ["onemarinex.db", "app.db"]

for db_file in db_files:
    print(f"\n{'='*80}")
    print(f"Trying database: {db_file}")
    print(f"{'='*80}")

    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()

        # Get all tables first
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        print(f"Tables: {[t[0] for t in tables]}")

        # Try to find the restricted words table
        restricted_word_table = None
        for table_name, in tables:
            if "restrict" in table_name.lower() or "word" in table_name.lower():
                restricted_word_table = table_name
                break

        if restricted_word_table:
            print(f"Found table: {restricted_word_table}")

            # Get column names
            cursor.execute(f"PRAGMA table_info({restricted_word_table})")
            columns = cursor.fetchall()
            print(f"Columns: {[c[1] for c in columns]}")

            # Try to query
            cursor.execute(f"SELECT * FROM {restricted_word_table} WHERE is_active = 1 LIMIT 30")
            all_words = cursor.fetchall()
            print(f"Total active words: {len(all_words)}")

            # Check for jagadeesh and raju
            target_words = ["jagadeesh", "raju"]

            print(f"\n{'='*80}")
            print("CHECKING FOR TARGET WORDS IN DATABASE")
            print(f"{'='*80}")

            for target in target_words:
                print(f"\nSearching for: {repr(target)}")
                found = False
                for word_row in all_words:
                    # Assume second column is 'word'
                    word = word_row[1] if len(word_row) > 1 else str(word_row)
                    if target.lower() in str(word).lower():
                        found = True
                        print(f"  Found: {word_row}")

                if not found:
                    print(f"  NOT FOUND in database")

        else:
            print("No restricted word table found")

        conn.close()

    except Exception as e:
        print(f"Error with {db_file}: {e}")

print(f"\n{'='*80}")
