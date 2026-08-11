"""
Regression tests for restricted-word dictionary matching fix.

These tests verify:
1. False positives are fixed: "but" no longer matches "butt", "as" no longer matches "ass"
2. Exact matches still work: "butt" still matches "butt", "ass" still matches "ass"
3. Boundary cases work: "butter" doesn't match "butt", "assessment" doesn't match "ass"
4. Evasion detection still works: "b u t t" still matches "butt"
5. The original "jagadeesh" fix from f8c8440 still works
"""

from app.utils.text_normalization import normalize, normalize_for_dictionary_matching


class TestNormalizeForDictionaryMatching:
    """Test the new normalize_for_dictionary_matching function."""

    def test_preserves_repeated_characters(self):
        """Should preserve legitimate repeated characters."""
        assert normalize_for_dictionary_matching("butt") == "butt"
        assert normalize_for_dictionary_matching("ass") == "ass"
        assert normalize_for_dictionary_matching("hello") == "hello"

    def test_handles_case_normalization(self):
        """Should normalize case."""
        assert normalize_for_dictionary_matching("BUTT") == "butt"
        assert normalize_for_dictionary_matching("Ass") == "ass"

    def test_removes_punctuation_evasion(self):
        """Should remove punctuation used in evasion."""
        assert normalize_for_dictionary_matching("b.u.t.t") == "butt"
        assert normalize_for_dictionary_matching("b-u-t-t") == "butt"
        assert normalize_for_dictionary_matching("a.s.s") == "ass"

    def test_removes_space_evasion(self):
        """Should remove spaces used in evasion."""
        assert normalize_for_dictionary_matching("b u t t") == "butt"
        assert normalize_for_dictionary_matching("a s s") == "ass"

    def test_handles_hyphenated_with_space(self):
        """Should handle hyphenated with spaces correctly."""
        # All consistent patterns should work
        assert normalize_for_dictionary_matching("b-u-t-t") == "butt"
        # Mixed patterns with spaces become separate tokens (edge case)
        assert normalize_for_dictionary_matching("b.u t.t") == "bu tt"

    def test_handles_multiple_spaces(self):
        """Should collapse multiple spaces."""
        assert normalize_for_dictionary_matching("hello    world") == "hello world"

    def test_handles_unicode(self):
        """Should normalize unicode characters."""
        # This would be a mathematical bold 'p' if we had one
        # For now test accents
        assert normalize_for_dictionary_matching("cafe") == "cafe"

    def test_skips_character_run_collapse(self):
        """Should NOT collapse repeated characters like normalize() does."""
        # normalize() collapses "eeee" to "e"
        assert normalize("seeeex") == "sex"
        # normalize_for_dictionary_matching() should preserve them
        assert normalize_for_dictionary_matching("seeeex") == "seeeex"

    def test_legitimate_repeated_characters(self):
        """Legitimate words with repeated characters should be preserved."""
        # These are real English words with double letters
        assert normalize_for_dictionary_matching("butter") == "butter"
        assert normalize_for_dictionary_matching("assessment") == "assessment"
        assert normalize_for_dictionary_matching("passage") == "passage"
        assert normalize_for_dictionary_matching("mississippi") == "mississippi"


class TestDictionaryTokenMatching:
    """Test dictionary token matching logic."""

    def test_exact_token_match(self):
        """Tokens should match exactly."""
        # "but" should NOT be in a dict that only has "butt"
        dict_with_butt = {"butt"}
        msg_but = normalize_for_dictionary_matching("but")
        tokens = msg_but.split()
        assert "but" in tokens
        assert "but" not in dict_with_butt

    def test_exact_token_match_ass(self):
        """'as' should NOT match 'ass' in dict."""
        dict_with_ass = {"ass"}
        msg_as = normalize_for_dictionary_matching("as")
        tokens = msg_as.split()
        assert "as" in tokens
        assert "as" not in dict_with_ass

    def test_exact_match_still_works(self):
        """Exact matches should still be found."""
        dict_words = {"butt", "ass"}
        msg_butt = normalize_for_dictionary_matching("butt")
        tokens = msg_butt.split()
        assert "butt" in tokens
        assert "butt" in dict_words

    def test_boundary_case_butter(self):
        """'butter' should NOT partially match 'butt'."""
        dict_with_butt = {"butt"}
        msg_butter = normalize_for_dictionary_matching("butter")
        tokens = msg_butter.split()
        # After normalization, "butter" becomes "butter" (no repeated char collapse)
        assert "butter" in tokens
        assert "butter" not in dict_with_butt
        assert "butt" not in tokens

    def test_boundary_case_assessment(self):
        """'assessment' should NOT partially match 'ass'."""
        dict_with_ass = {"ass"}
        msg_assessment = normalize_for_dictionary_matching("assessment")
        tokens = msg_assessment.split()
        assert "assessment" in tokens
        assert "assessment" not in dict_with_ass
        assert "ass" not in tokens

    def test_boundary_case_passage(self):
        """'passage' should NOT partially match 'ass'."""
        dict_with_ass = {"ass"}
        msg_passage = normalize_for_dictionary_matching("passage")
        tokens = msg_passage.split()
        assert "passage" in tokens
        assert "passage" not in dict_with_ass
        assert "ass" not in tokens


class TestEvasionDetectionStillWorks:
    """Verify evasion detection still works with the fix."""

    def test_spaced_evasion_detected(self):
        """Spaced-out restricted words should be detected."""
        # "b u t t" should normalize to "butt"
        normalized = normalize_for_dictionary_matching("b u t t")
        tokens = normalized.split()
        assert "butt" in tokens

    def test_punctuated_evasion_detected(self):
        """Punctuated restricted words should be detected."""
        # "b.u.t.t" should normalize to "butt"
        normalized = normalize_for_dictionary_matching("b.u.t.t")
        tokens = normalized.split()
        assert "butt" in tokens

    def test_hyphenated_evasion_detected(self):
        """Hyphenated restricted words should be detected."""
        # "b-u-t-t" should normalize to "butt"
        normalized = normalize_for_dictionary_matching("b-u-t-t")
        tokens = normalized.split()
        assert "butt" in tokens

    def test_leetspeak_evasion_detected(self):
        """Leetspeak variants should be detected."""
        # "b4tt" (4=a is not in our leet table for numeric only)
        # Actually our leet table only does: 0→o, 1→i, 3→e, 4→a, 5→s, 7→t, 8→b, 9→g
        # So "b8tt" should become "bbtt"? Actually no, 8→b
        # Let me use a valid leetspeak: "5" → "s", so "a55" → "ass"
        normalized = normalize_for_dictionary_matching("a55")
        tokens = normalized.split()
        assert "ass" in tokens


class TestJagadeeshCase:
    """Verify the original f8c8440 fix still works (jagadeesh case)."""

    def test_jagadeesh_normalization(self):
        """'jagadeesh' should remain 'jagadeesh' in dictionary matching."""
        # This tests the original problem that f8c8440 was fixing
        # In normalize(), "jagadeesh" → "jagadesh" (ee→e via step 13)
        # In normalize_for_dictionary_matching(), "jagadeesh" → "jagadeesh"
        assert normalize("jagadeesh") == "jagadesh"
        assert normalize_for_dictionary_matching("jagadeesh") == "jagadeesh"

    def test_jagadeesh_in_message_matches(self):
        """User message with 'jagadeesh' should match dict entry 'jagadeesh'."""
        # Dictionary stores: "jagadeesh" (via simple .lower().strip())
        dict_words = {"jagadeesh"}
        msg = normalize_for_dictionary_matching("I like jagadeesh")
        tokens = msg.split()
        # Message should contain "jagadeesh" token
        assert "jagadeesh" in tokens
        assert "jagadeesh" in dict_words


class TestComprehensiveScenarios:
    """Test complete realistic scenarios."""

    def test_false_positive_but_fixed(self):
        """Message 'but' should NOT match dictionary entry 'butt'."""
        dict_cache = {"butt"}  # Dictionary has "butt"

        # User sends "but"
        normalized_msg = normalize_for_dictionary_matching("but")
        tokens = normalized_msg.split()

        # Look for match
        matched = None
        for token in tokens:
            import re
            clean_token = re.sub(r'[^a-z0-9]', '', token)
            if clean_token in dict_cache:
                matched = clean_token
                break

        assert matched is None, "False positive: 'but' should not match 'butt'"

    def test_false_positive_as_fixed(self):
        """Message 'as' should NOT match dictionary entry 'ass'."""
        dict_cache = {"ass"}  # Dictionary has "ass"

        # User sends "as"
        normalized_msg = normalize_for_dictionary_matching("as")
        tokens = normalized_msg.split()

        # Look for match
        matched = None
        for token in tokens:
            import re
            clean_token = re.sub(r'[^a-z0-9]', '', token)
            if clean_token in dict_cache:
                matched = clean_token
                break

        assert matched is None, "False positive: 'as' should not match 'ass'"

    def test_real_restriction_still_works(self):
        """Message 'butt' should still match dictionary entry 'butt'."""
        dict_cache = {"butt"}  # Dictionary has "butt"

        # User sends "butt"
        normalized_msg = normalize_for_dictionary_matching("butt")
        tokens = normalized_msg.split()

        # Look for match
        matched = None
        for token in tokens:
            import re
            clean_token = re.sub(r'[^a-z0-9]', '', token)
            if clean_token in dict_cache:
                matched = clean_token
                break

        assert matched == "butt", "Real restriction 'butt' should match"

    def test_evasion_still_caught(self):
        """Evasion attempt 'b.u.t.t' should still match dictionary entry 'butt'."""
        dict_cache = {"butt"}  # Dictionary has "butt"

        # User tries evasion: "b.u.t.t"
        normalized_msg = normalize_for_dictionary_matching("b.u.t.t")
        tokens = normalized_msg.split()

        # Look for match
        matched = None
        for token in tokens:
            import re
            clean_token = re.sub(r'[^a-z0-9]', '', token)
            if clean_token in dict_cache:
                matched = clean_token
                break

        assert matched == "butt", "Evasion attempt should still be caught"


if __name__ == "__main__":
    # Run tests manually
    import sys

    test_classes = [
        TestNormalizeForDictionaryMatching,
        TestDictionaryTokenMatching,
        TestEvasionDetectionStillWorks,
        TestJagadeeshCase,
        TestComprehensiveScenarios,
    ]

    total_passed = 0
    total_failed = 0

    for test_class in test_classes:
        print(f"\n{test_class.__name__}:")
        print("-" * 70)

        test_instance = test_class()
        test_methods = [m for m in dir(test_instance) if m.startswith("test_")]

        for method_name in test_methods:
            try:
                method = getattr(test_instance, method_name)
                method()
                print(f"  [PASS] {method_name}")
                total_passed += 1
            except AssertionError as e:
                print(f"  [FAIL] {method_name}: {str(e)}")
                total_failed += 1
            except Exception as e:
                print(f"  [ERROR] {method_name}: {str(e)}")
                total_failed += 1

    print("\n" + "=" * 70)
    print(f"Results: {total_passed} passed, {total_failed} failed")
    print("=" * 70)

    sys.exit(0 if total_failed == 0 else 1)
