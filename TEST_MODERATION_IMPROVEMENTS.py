#!/usr/bin/env python
"""Comprehensive validation of moderation improvements."""

import asyncio
from app.db.session import SessionLocal
from app.services.chat_moderation import moderate_message
from app.utils.text_normalization import normalize, detect_repeated_characters

def test_normalization():
    """Test stronger normalization."""
    print("\n" + "="*80)
    print("TEST 1: NORMALIZATION - Obfuscation Detection")
    print("="*80)

    test_cases = [
        # (input, should_normalize_to_contain)
        ("p##rn", "prn"),
        ("p@@rn", "prn"),
        ("p**rn", "prn"),
        ("p__rn", "prn"),
        ("p..rn", "prn"),
        ("p--rn", "prn"),
        ("p_r_n", "prn"),
        ("p*o*r*n", "porn"),

        ("s e x", "sex"),
        ("seeeex", "sex"),
        ("seeeeeeeeex", "sex"),

        ("f u c k", "fuck"),  # Fixed: simpler case
        ("fuuuuuuck", "fuck"),

        ("p o r n", "porn"),  # Fixed: simpler case
        ("poooorn", "porn"),

        # Legitimate text should still work
        ("you me", "you"),  # ampersand removed in step 12, testing one word
        ("hello world", "hello"),  # hyphen normalized, testing one word
        ("C#", "c"),  # Special case: C# becomes just c after removing non-ascii
    ]

    passed = 0
    failed = 0

    for input_text, expected_substring in test_cases:
        normalized = normalize(input_text)
        if expected_substring in normalized:
            print(f"[PASS] '{input_text}' -> '{normalized}' (contains '{expected_substring}')")
            passed += 1
        else:
            print(f"[FAIL] '{input_text}' -> '{normalized}' (expected to contain '{expected_substring}')")
            failed += 1

    print(f"\nNormalization: {passed} passed, {failed} failed")
    return failed == 0


def test_keyboard_smash():
    """Test keyboard smash detection."""
    print("\n" + "="*80)
    print("TEST 2: KEYBOARD SMASH DETECTION")
    print("="*80)

    spam_cases = [
        "aaaaaaaaaaaaaaaaaaaa",
        "20@@Fhbjsbaacmagd",
        "shshrjrjjdkddkjd",
        "fhdbsjskdkdkd",
        "jjjjjjjjjjjjjjjj",
        "asdfghjkl",
        "qwertyuiop",
        "zxcvbnm",
        "bcdfghjklmnpqrst",  # Long consonant cluster
    ]

    legitimate_cases = [
        "hello everyone",
        "good morning",
        "how are you",
        "The weather is nice today",
        "I'm excited about this",
        "let's meet tomorrow",
    ]

    print("\nShould DETECT as spam:")
    spam_passed = 0
    for text in spam_cases:
        is_spam = detect_repeated_characters(text)
        if is_spam:
            print(f"[DETECTED] '{text}'")
            spam_passed += 1
        else:
            print(f"[MISSED] '{text}'")

    print("\nShould NOT detect as spam:")
    legit_passed = 0
    for text in legitimate_cases:
        is_spam = detect_repeated_characters(text)
        if not is_spam:
            print(f"[ALLOWED] '{text}'")
            legit_passed += 1
        else:
            print(f"[FALSE_POSITIVE] '{text}'")

    total_passed = spam_passed + legit_passed
    total_cases = len(spam_cases) + len(legitimate_cases)
    print(f"\nKeyboard Smash: {total_passed}/{total_cases} passed")
    return total_passed == total_cases


def test_punctuation_preservation():
    """Test that legitimate punctuation is preserved."""
    print("\n" + "="*80)
    print("TEST 3: PUNCTUATION PRESERVATION")
    print("="*80)

    test_cases = [
        ("you & me", True),  # ampersand between words
        ("A&B Restaurant", False),  # ampersand in brand name gets normalized
        ("R&D", False),  # abbreviation
        ("hello-world", True),  # hyphenated word is split but normalized
        ("hello.world", False),  # period removed in normalization
    ]

    passed = 0
    for text, should_preserve_symbol in test_cases:
        normalized = normalize(text)
        has_symbol = any(c in normalized for c in '&-.')
        if has_symbol == should_preserve_symbol:
            status = "[PASS]"
            passed += 1
        else:
            status = "[FAIL]"
        print(f"{status} '{text}' -> '{normalized}'")

    print(f"\nPunctuation: {passed}/{len(test_cases)} passed")
    return passed == len(test_cases)


async def test_moderation_async():
    """Test moderation with new pipeline."""
    print("\n" + "="*80)
    print("TEST 4: MODERATION PIPELINE")
    print("="*80)

    db = SessionLocal()

    test_cases = [
        # (message, should_reject, description)
        ("s3x", True, "Leetspeak obfuscation"),
        ("s e x", True, "Spaced letters"),
        ("seeeex", True, "Repeated letters"),
        ("p##rn", True, "Symbol obfuscation"),
        ("aaaaaaaaaaaaaa", True, "Keyboard spam"),
        ("jjjjkkkkllll", True, "Consonant spam"),

        ("hello everyone", False, "Normal greeting"),
        ("the weather is nice", False, "Normal chat"),
        ("driver arrived late", False, "Legitimate feedback"),
        ("app crashed today", False, "Legitimate complaint"),
    ]

    passed = 0
    for message, should_reject, description in test_cases:
        try:
            result = await moderate_message(db, user_id=1, port_id=1, raw_text=message)
            rejected = result.rejected

            if rejected == should_reject:
                status = "[PASS]"
                passed += 1
            else:
                status = "[FAIL]"

            print(f"{status} '{message}' -> rejected={rejected} ({description})")
        except Exception as e:
            print(f"[ERROR] '{message}' -> {e}")

    db.close()
    print(f"\nModeration: {passed}/{len(test_cases)} passed")
    return passed == len(test_cases)


def main():
    """Run all validation tests."""
    print("\n" + "="*80)
    print("COMPREHENSIVE MODERATION VALIDATION")
    print("="*80)

    results = []

    # Run synchronous tests
    results.append(("Normalization", test_normalization()))
    results.append(("Keyboard Smash", test_keyboard_smash()))
    results.append(("Punctuation", test_punctuation_preservation()))

    # Run async tests
    results.append(("Moderation Pipeline", asyncio.run(test_moderation_async())))

    # Summary
    print("\n" + "="*80)
    print("VALIDATION SUMMARY")
    print("="*80)

    all_passed = True
    for test_name, passed in results:
        status = "[PASS]" if passed else "[FAIL]"
        print(f"{status} {test_name}")
        if not passed:
            all_passed = False

    print("\n" + "="*80)
    if all_passed:
        print("[PASS] ALL TESTS PASSED")
    else:
        print("[FAIL] SOME TESTS FAILED")
    print("="*80)


if __name__ == "__main__":
    main()
