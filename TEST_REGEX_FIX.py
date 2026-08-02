#!/usr/bin/env python
"""Test regex patterns for Step 10 fix before implementation."""

import re

def test_regex(pattern, test_cases, description):
    """Test a regex pattern against test cases."""
    print(f"\n{'='*70}")
    print(f"Testing: {description}")
    print(f"Pattern: {pattern}")
    print(f"{'='*70}")

    regex = re.compile(pattern)

    should_match = test_cases["should_match"]
    should_not_match = test_cases["should_not_match"]

    passed = 0
    failed = 0

    print("\nShould MATCH (detect obfuscation):")
    for text in should_match:
        match = regex.search(text)
        if match:
            print(f"  [PASS] '{text}' -> matched '{match.group(0)}'")
            passed += 1
        else:
            print(f"  [FAIL] '{text}' -> NO MATCH")
            failed += 1

    print("\nShould NOT MATCH (preserve normal text):")
    for text in should_not_match:
        match = regex.search(text)
        if not match:
            print(f"  [PASS] '{text}' -> no match")
            passed += 1
        else:
            print(f"  [FAIL] '{text}' -> matched '{match.group(0)}'")
            failed += 1

    print(f"\nResult: {passed} passed, {failed} failed")
    return failed == 0

# Test cases
test_cases = {
    "should_match": [
        "p o r n",
        "s e x",
        "f u c k",
        "(p o r n)",
        "p o r n.",
        "p o r n!",
        "p o r n,",
        "he likes p o r n",
        "start p o r n end",
        " s e x ",
    ],
    "should_not_match": [
        "i like porn",
        "lets kill him",
        "raju is good",
        "good morning everyone",
        "he likes porn",
        "p",
        "po",
    ]
}

# Test different regex patterns
patterns = [
    (r"(?:^|\s)[a-z](?:\s[a-z])+(?:\s|$)", "Original proposal (may fail with punctuation)"),
    (r"(?:^|\s|\(|\")[a-z](?:\s[a-z])+(?:\s|$|\.|\!|\,|\))", "With punctuation in boundaries"),
    (r"\b[a-z](?:\s[a-z])+\b", "Word boundaries (may not work with spaces)"),
    (r"(?:^|[\s\(\"])[a-z](?:\s[a-z])+(?=[\s\.\!\,\)\"\$]|$)", "Lookahead for end boundary"),
]

all_passed = []
for pattern, description in patterns:
    try:
        result = test_regex(pattern, test_cases, description)
        all_passed.append((description, result))
    except Exception as e:
        print(f"\n[ERROR] Pattern error: {e}")
        all_passed.append((description, False))

# Summary
print("\n" + "="*70)
print("SUMMARY")
print("="*70)
for desc, passed in all_passed:
    status = "[PASS]" if passed else "[FAIL]"
    print(f"{status}: {desc}")

best = [desc for desc, passed in all_passed if passed]
if best:
    print(f"\n[SUCCESS] Best patterns: {best}")
else:
    print(f"\n[WARNING] No patterns passed all tests. Need to refine further.")
