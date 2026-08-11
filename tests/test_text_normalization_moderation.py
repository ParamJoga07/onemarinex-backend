"""
Regression tests for text normalization and spam detection.

These tests verify:
1. False positive fix: Restaurant reviews with diverse vocabulary are no longer rejected
2. Spam detection still works: Keyboard smash, repeated chars, and gibberish are caught
3. Edge cases: Mixed content, punctuation, numbers in legitimate text
"""

from app.utils.text_normalization import (
    normalize,
    detect_repeated_characters,
    _is_keyboard_smash,
)


def run_tests():
    """Run all tests and report results."""
    tests = [
        ("test_legitimate_pub_review_1", test_legitimate_pub_review_1),
        ("test_legitimate_pub_review_2", test_legitimate_pub_review_2),
        ("test_legitimate_diverse_vocab", test_legitimate_diverse_vocab),
        ("test_legitimate_with_quality_feedback", test_legitimate_with_quality_feedback),
        ("test_legitimate_brand_name", test_legitimate_brand_name),
        ("test_legitimate_complex_sentence", test_legitimate_complex_sentence),
        ("test_keyboard_pattern_asdfghjkl", test_keyboard_pattern_asdfghjkl),
        ("test_keyboard_pattern_qwertyuiop", test_keyboard_pattern_qwertyuiop),
        ("test_repeated_characters_aaaa", test_repeated_characters_aaaa),
        ("test_repeated_characters_xxxx", test_repeated_characters_xxxx),
        ("test_consonant_heavy_gibberish", test_consonant_heavy_gibberish),
        ("test_random_consonant_clusters", test_random_consonant_clusters),
        ("test_random_mixed_gibberish", test_random_mixed_gibberish),
        ("test_keyboard_smash_detects_low_vowels", test_keyboard_smash_detects_low_vowels),
        ("test_legitimate_text_passes", test_legitimate_text_passes),
        ("test_consonant_cluster_detection", test_consonant_cluster_detection),
        ("test_normalize_removes_punctuation", test_normalize_removes_punctuation),
        ("test_normalize_lowercase", test_normalize_lowercase),
        ("test_normalize_spaces", test_normalize_spaces),
        ("test_short_text", test_short_text),
        ("test_text_with_numbers", test_text_with_numbers),
        ("test_text_with_punctuation", test_text_with_punctuation),
        ("test_mixed_case_and_symbols", test_mixed_case_and_symbols),
        ("test_exactly_20_percent_vowels", test_exactly_20_percent_vowels),
        ("test_just_above_vowel_threshold", test_just_above_vowel_threshold),
    ]

    passed = 0
    failed = 0
    failures = []

    for test_name, test_func in tests:
        try:
            test_func()
            print("[PASS] %s" % test_name)
            passed += 1
        except AssertionError as e:
            print("[FAIL] %s: %s" % (test_name, str(e)))
            failed += 1
            failures.append((test_name, str(e)))
        except Exception as e:
            print("[ERROR] %s: %s" % (test_name, str(e)))
            failed += 1
            failures.append((test_name, str(e)))

    print("\n" + "="*70)
    print("Test Results: %d passed, %d failed out of %d total" % (passed, failed, passed + failed))
    print("="*70)

    if failures:
        print("\nFailures:")
        for test_name, error in failures:
            print("  - %s: %s" % (test_name, error))

    return passed, failed

# Test implementations
def test_legitimate_pub_review_1():
    text = "Shack is great pub, the ambience is great"
    assert not detect_repeated_characters(text), (
        f"Legitimate review should not be detected as spam: {text}"
    )

def test_legitimate_pub_review_2():
    text = "Great food, nice ambience, friendly staff"
    assert not detect_repeated_characters(text), (
        f"Legitimate review should not be detected as spam: {text}"
    )

def test_legitimate_diverse_vocab():
    text = "We had an amazing evening at the pub"
    assert not detect_repeated_characters(text), (
        f"Legitimate review with diverse vocabulary should pass: {text}"
    )

def test_legitimate_with_quality_feedback():
    text = "The food and drinks were superb"
    assert not detect_repeated_characters(text), (
        f"Multi-attribute feedback should be accepted: {text}"
    )

def test_legitimate_brand_name():
    text = "Myz Uno was also good"
    assert not detect_repeated_characters(text), (
        f"Message with brand names should be accepted: {text}"
    )

def test_legitimate_complex_sentence():
    text = "Even we visited, it is a great place for drinks"
    assert not detect_repeated_characters(text), (
        f"Complex legitimate sentence should be accepted: {text}"
    )

def test_keyboard_pattern_asdfghjkl():
    text = "asdfghjkl"
    assert detect_repeated_characters(text), (
        f"Keyboard pattern 'asdfghjkl' should be detected as spam"
    )

def test_keyboard_pattern_qwertyuiop():
    text = "qwertyuiop"
    assert detect_repeated_characters(text), (
        f"Keyboard pattern 'qwertyuiop' should be detected as spam"
    )

def test_repeated_characters_aaaa():
    text = "aaaaaaaaaa"
    assert detect_repeated_characters(text), (
        f"Repeated 'a' characters should be detected as spam"
    )

def test_repeated_characters_xxxx():
    text = "xxxxxxxxxxxx"
    assert detect_repeated_characters(text), (
        f"Repeated 'x' characters should be detected as spam"
    )

def test_consonant_heavy_gibberish():
    text = "jdhdjdhd"
    assert detect_repeated_characters(text), (
        f"Consonant-heavy gibberish should be detected (low vowel ratio)"
    )

def test_random_consonant_clusters():
    text = "bcdfghjklmn"
    assert detect_repeated_characters(text), (
        f"All-consonant string should be detected (0% vowels)"
    )

def test_random_mixed_gibberish():
    text = "xkqwzpmnb"
    assert detect_repeated_characters(text), (
        f"Random gibberish mix should be detected (low vowel ratio)"
    )

def test_keyboard_smash_detects_low_vowels():
    text = "jdhdjdhd"
    assert _is_keyboard_smash(text), (
        f"Should detect 0% vowel ratio as smash"
    )

def test_legitimate_text_passes():
    text = "the quick brown fox"
    assert not _is_keyboard_smash(text), (
        f"Normal text with adequate vowels should pass smash detection"
    )

def test_consonant_cluster_detection():
    text = "bcdfghjklmnpqrst"
    assert _is_keyboard_smash(text), (
        f"Should detect via vowel ratio or consonant clusters"
    )

def test_normalize_removes_punctuation():
    text = "Shack is great pub, the ambience is great"
    normalized = normalize(text)
    assert "," not in normalized, "Normalized text should not contain punctuation"
    assert "shack is great pub the ambience is great" == normalized

def test_normalize_lowercase():
    text = "HELLO WORLD"
    normalized = normalize(text)
    assert normalized == "helo world", (
        f"Expected 'helo world' (character run collapse), got '{normalized}'"
    )

def test_normalize_spaces():
    text = "hello    world"
    normalized = normalize(text)
    # Character run collapsing collapses multiple spaces too, but also multiple identical chars
    # So "hello" becomes "helo" (double l) and "    " becomes " " (single space)
    assert normalized == "helo world", (
        f"Expected 'helo world' (char run collapse), got '{normalized}'"
    )

def test_short_text():
    text = "ok"
    assert not detect_repeated_characters(text), (
        f"Short legitimate text should not be flagged"
    )

def test_text_with_numbers():
    text = "visited 3 times in 2024"
    assert not detect_repeated_characters(text), (
        f"Legitimate text with numbers should pass"
    )

def test_text_with_punctuation():
    text = "The restaurant's food, drinks, and ambience are great!"
    assert not detect_repeated_characters(text), (
        f"Legitimate text with punctuation should pass after normalization"
    )

def test_mixed_case_and_symbols():
    # Test mixed case and symbols in legitimate review
    text = "Lovely place! Good food & service here"
    result = detect_repeated_characters(text)
    assert not result, (
        f"Legitimate text with mixed case should pass"
    )

def test_exactly_20_percent_vowels():
    text = "aeiobcdfghjklmnpqrstvwxyz"
    assert _is_keyboard_smash(text), (
        f"19.2% vowels should trigger detection"
    )

def test_just_above_vowel_threshold():
    # 5 vowels (a,e,i,o,u) out of 10 chars = 50% > 20% threshold
    # Interleaved pattern avoids consonant clusters
    text = "abecidofug"
    assert not _is_keyboard_smash(text), (
        f"50% vowels with no consonant clusters should pass keyboard smash detection"
    )

if __name__ == "__main__":
    passed, failed = run_tests()
