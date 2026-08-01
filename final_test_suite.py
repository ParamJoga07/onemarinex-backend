#!/usr/bin/env python
"""Final comprehensive moderation test suite - all tests."""
import re
from app.utils.text_normalization import normalize
from app.db.session import engine
from sqlalchemy import text
from datetime import datetime

def load_restricted_words():
    """Load restricted words from database."""
    single_words = set()

    with engine.connect() as conn:
        words = conn.execute(text("SELECT word FROM chat_restricted_words WHERE is_active")).fetchall()
        for w in words:
            single_words.add(w[0])

    return single_words

def check_dictionary(normalized: str, single_words) -> str:
    """Check if message contains restricted words."""
    tokens = normalized.split()

    for token in tokens:
        clean_token = re.sub(r'[^a-z0-9]', '', token)
        if clean_token and clean_token in single_words:
            return clean_token

    return None

# Test suite with expected results
TEST_SUITE = {
    "Normal Messages": [
        ("Hello", False, "clean message"),
        ("Good morning", False, "clean message"),
        ("I need a taxi", False, "clean message"),
        ("Where is the nearest mall?", False, "clean message"),
    ],

    "Profanity": [
        ("sex", True, "exact match"),
        ("porn", True, "exact match"),
        ("boobs", True, "exact match"),
        ("fuck", True, "exact match"),
        ("shit", True, "exact match"),
        ("asshole", True, "exact match"),
    ],

    "Profanity in Sentences": [
        ("porn is good", True, "word in sentence"),
        ("I like sex", True, "word in sentence"),
        ("there are prostitutes", True, "plural word"),
        ("drugs are available here", True, "word in sentence"),
        ("where can I find escorts?", True, "plural with punctuation"),
        ("prostitutes there?", True, "plural with punctuation"),
        ("are any prostitutes available?", True, "phrase with punctuation"),
    ],

    "Obfuscated Profanity": [
        ("s.e.x", True, "dot obfuscation"),
        ("p0rn", True, "leet speak"),
        ("f**k", True, "asterisk obfuscation"),
        ("sh!t", True, "exclamation obfuscation"),
        ("f-u-c-k", True, "hyphen obfuscation"),
    ],

    "Hate Speech": [
        ("black people fuck off", True, "combines profanity + slur"),
        ("chinese are idiots", True, "targeted insult"),
        ("white people are idiots", True, "targeted insult"),
    ],

    "Harassment": [
        ("Joshan is idiot", True, "personal attack"),
        ("Jagadeesh is idiot", True, "personal attack"),
        ("You are stupid", True, "direct insult"),
        ("I hate you", True, "personal attack"),
    ],

    "Violence/Threats": [
        ("lets kill him", True, "violence"),
        ("I will murder you", True, "threat"),
        ("I will beat you", True, "threat"),
    ],

    "Spam/Gibberish": [
        ("hgfkguilhiojojiiojoihiuhnjnkjnb", True, "keyboard smash"),
        ("@@4444#$%^@", True, "symbol spam"),
        ("asdfasdfasdfasdf", True, "keyboard smash"),
        ("qwertyuioplkjh", True, "keyboard smash"),
    ],

    "Language Detection": [
        ("Hello", False, "English"),
        ("ela unnaru", True, "Telugu transliteration"),
        ("dengutha bagunnara", True, "Telugu transliteration"),
        ("bagunnara", True, "Telugu transliteration"),
    ],
}

def run_tests():
    """Run all tests."""
    single_words = load_restricted_words()

    print("=" * 120)
    print("FINAL COMPREHENSIVE MODERATION TEST SUITE")
    print("=" * 120)
    print()

    total_tests = 0
    passed_tests = 0
    failed_tests = []

    for category, tests in TEST_SUITE.items():
        print(f"\n{category}")
        print("-" * 120)

        for message, should_reject, note in tests:
            total_tests += 1
            normalized = normalize(message)

            # Dictionary check
            matched = check_dictionary(normalized, single_words)
            dict_reject = matched is not None

            # For now, only do dictionary checking
            actual_reject = dict_reject

            # Determine pass/fail
            test_pass = actual_reject == should_reject
            if test_pass:
                passed_tests += 1
                status = "PASS"
            else:
                failed_tests.append({
                    'category': category,
                    'message': message,
                    'expected': should_reject,
                    'actual': actual_reject,
                    'note': note,
                    'matched': matched
                })
                status = "FAIL"

            msg_display = message[:40] if len(message) <= 40 else message[:37] + "..."
            expected_str = "Reject" if should_reject else "Allow"
            actual_str = "Reject" if actual_reject else "Allow"
            matched_str = f"({matched})" if matched else ""

            print(f"  {status} | {msg_display:43} | Exp: {expected_str:6} Act: {actual_str:6} {matched_str:15} | {note}")

    # Summary
    print("\n" + "=" * 120)
    print("TEST SUMMARY")
    print("=" * 120)
    print(f"Total Tests:    {total_tests}")
    print(f"Passed:         {passed_tests}")
    print(f"Failed:         {len(failed_tests)}")
    if total_tests > 0:
        print(f"Pass Rate:      {(passed_tests/total_tests*100):.1f}%")
    print()

    if failed_tests:
        print("\n" + "=" * 120)
        print("FAILED TESTS DETAILS")
        print("=" * 120)
        for f in failed_tests:
            print(f"\n{f['category']}: {f['message']}")
            print(f"  Expected: {'Reject' if f['expected'] else 'Allow'}")
            print(f"  Actual:   {'Reject' if f['actual'] else 'Allow'}")
            print(f"  Matched:  {f['matched']}")
            print(f"  Note:     {f['note']}")

    return passed_tests, total_tests, failed_tests

if __name__ == "__main__":
    passed, total, failed = run_tests()
    exit(0 if len(failed) == 0 else 1)
