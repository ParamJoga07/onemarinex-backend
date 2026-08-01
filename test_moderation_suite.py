#!/usr/bin/env python
"""Comprehensive moderation test suite."""
import asyncio
import sys
import os
from datetime import datetime
from typing import List, Dict, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.db.session import SessionLocal
from app.services.chat_moderation import moderate_message, reload_restricted_words

# Test categories
NORMAL_MESSAGES = [
    ("Hello", False),
    ("Good morning", False),
    ("I need a taxi", False),
    ("Where is the nearest mall?", False),
]

PROFANITY = [
    ("sex", True),
    ("porn", True),
    ("boobs", True),
    ("fuck", True),
    ("shit", True),
    ("asshole", True),
]

PROFANITY_IN_SENTENCES = [
    ("porn is good", True),
    ("I like sex", True),
    ("there are prostitutes", True),
    ("drugs are available here", True),
    ("where can I find escorts?", True),
    ("prostitutes there?", True),
    ("are any prostitutes available?", True),
]

OBFUSCATED_PROFANITY = [
    ("s.e.x", True),
    ("p0rn", True),
    ("f**k", True),
    ("sh!t", True),
]

HATE_SPEECH = [
    ("black people fuck off", True),
    ("chinese are idiots", True),
    ("white people are idiots", True),
]

HARASSMENT = [
    ("Joshan is idiot", True),
    ("Jagadeesh is idiot", True),
    ("You are stupid", True),
    ("I hate you", True),
]

VIOLENCE_THREATS = [
    ("lets kill him", True),
    ("I will murder you", True),
    ("I will beat you", True),
]

SPAM_KEYBOARD_SMASH = [
    ("hgfkguilhiojojiiojoihiuhnjnkjnb", True),
    ("@@4444#$%^@", True),
    ("asdfasdfasdfasdf", True),
    ("qwertyuioplkjh", True),
    ("w98yydhnncvdscc", True),
]

LANGUAGE_DETECTION = [
    ("Hello", False),
    ("ela unnaru", True),
    ("bagunnara", True),
    ("dengutha", True),
]

RESTRICTED_WORDS_IN_SENTENCES = [
    ("porn is good", True),
    ("I like sex", True),
    ("there are prostitutes", True),
    ("where can I buy drugs?", True),
]

TEST_SUITES = {
    "Normal Messages": NORMAL_MESSAGES,
    "Profanity": PROFANITY,
    "Profanity in Sentences": PROFANITY_IN_SENTENCES,
    "Obfuscated Profanity": OBFUSCATED_PROFANITY,
    "Hate Speech": HATE_SPEECH,
    "Harassment": HARASSMENT,
    "Violence/Threats": VIOLENCE_THREATS,
    "Spam/Keyboard Smash": SPAM_KEYBOARD_SMASH,
    "Language Detection": LANGUAGE_DETECTION,
    "Restricted Words in Sentences": RESTRICTED_WORDS_IN_SENTENCES,
}


async def run_tests():
    """Execute comprehensive test suite."""
    db = SessionLocal()

    # Reload dictionary to ensure it's fresh
    reload_restricted_words(db)

    results = []
    total = 0
    passed = 0
    failed = 0

    print("=" * 120)
    print("COMPREHENSIVE MODERATION TEST SUITE")
    print("=" * 120)
    print()

    for suite_name, tests in TEST_SUITES.items():
        print(f"\n{suite_name}")
        print("-" * 120)

        for message, should_reject in tests:
            total += 1
            try:
                result = await moderate_message(db, user_id=1, port_id=100, raw_text=message)
                actual_reject = result.rejected

                # Determine pass/fail
                test_pass = actual_reject == should_reject
                if test_pass:
                    passed += 1
                    status = "✅ PASS"
                else:
                    failed += 1
                    status = "❌ FAIL"

                # Format output
                msg_display = message[:40] if len(message) <= 40 else message[:37] + "..."
                expected = "Reject" if should_reject else "Allow"
                actual = "Reject" if actual_reject else "Allow"

                reason = f"{result.code} ({result.rejected_by})" if result.code else result.rejected_by

                print(f"  {status} | {msg_display:43} | Expected: {expected:6} | Actual: {actual:6} | {reason}")

                results.append({
                    "category": suite_name,
                    "message": message,
                    "expected": should_reject,
                    "actual": actual_reject,
                    "passed": test_pass,
                    "reason": reason
                })

            except Exception as e:
                total += 1
                failed += 1
                print(f"  ❌ ERROR | {message[:40]:43} | Exception: {str(e)[:50]}")
                results.append({
                    "category": suite_name,
                    "message": message,
                    "expected": should_reject,
                    "actual": None,
                    "passed": False,
                    "reason": f"Exception: {str(e)}"
                })

    # Summary
    print("\n" + "=" * 120)
    print("TEST SUMMARY")
    print("=" * 120)
    print(f"Total Tests:    {total}")
    print(f"Passed:         {passed}")
    print(f"Failed:         {failed}")
    print(f"Pass Rate:      {(passed/total*100):.1f}%")
    print()

    # Failed tests summary
    failed_tests = [r for r in results if not r["passed"]]
    if failed_tests:
        print("FAILED TESTS:")
        print("-" * 120)
        for r in failed_tests:
            print(f"  {r['category']:30} | {r['message'][:40]:43} | Expected: {str(r['expected']):5} | Got: {str(r['actual']):5}")
        print()

    return results, passed, failed, total


if __name__ == "__main__":
    results, passed, failed, total = asyncio.run(run_tests())
    sys.exit(0 if failed == 0 else 1)
