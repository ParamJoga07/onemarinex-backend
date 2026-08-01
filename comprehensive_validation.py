#!/usr/bin/env python
"""Comprehensive moderation validation - trace entire pipeline for every message."""
import re
from collections import Counter
from app.utils.text_normalization import normalize
from app.db.session import engine
from sqlalchemy import text

# Load restricted words
def load_restricted_words():
    single_words = set()
    with engine.connect() as conn:
        words = conn.execute(text("SELECT word FROM chat_restricted_words WHERE is_active")).fetchall()
        for w in words:
            single_words.add(w[0])
    return single_words

SINGLE_WORDS = load_restricted_words()

def trace_moderation(raw_text):
    """Trace complete moderation pipeline for a message."""

    # Step 1: Normalize
    normalized = normalize(raw_text)

    # Step 2: Tokenize
    tokens = normalized.split()

    # Step 3: Dictionary matching
    dict_match = None
    for token in tokens:
        clean_token = re.sub(r'[^a-z0-9]', '', token)
        if clean_token and clean_token in SINGLE_WORDS:
            dict_match = clean_token
            break

    # Step 4: Check for basic spam (raw text)
    letters = sum(1 for c in raw_text if c.isalpha())
    total = len(raw_text)
    symbol_spam = total > 0 and (letters / total) < 0.2

    # Step 5: Check keyboard smash
    letter_list = [c.lower() for c in raw_text if c.isalpha()]
    keyboard_smash = False
    if len(letter_list) > 8:
        letter_counts = Counter(letter_list)
        unique_letters = len(letter_counts)
        single_occurrence = sum(1 for count in letter_counts.values() if count == 1)
        keyboard_smash = unique_letters > len(letter_list) * 0.25 and single_occurrence > unique_letters * 0.4

    # Step 6: Determine final decision based on pipeline
    reason = ""
    final_decision = "ALLOW"

    if not normalized:
        final_decision = "REJECT"
        reason = "empty_message"
    elif symbol_spam:
        final_decision = "REJECT"
        reason = "symbol_spam"
    elif keyboard_smash:
        final_decision = "REJECT"
        reason = "keyboard_smash"
    elif dict_match:
        final_decision = "REJECT"
        reason = f"restricted_word: {dict_match}"

    return {
        'raw': raw_text,
        'normalized': normalized,
        'tokens': tokens,
        'dict_match': dict_match,
        'symbol_spam': symbol_spam,
        'keyboard_smash': keyboard_smash,
        'final_decision': final_decision,
        'reason': reason
    }

def print_result(result, test_name="", expected=""):
    """Print formatted test result."""
    raw = result['raw'][:40] if len(result['raw']) <= 40 else result['raw'][:37] + "..."
    normalized = result['normalized'][:40] if len(result['normalized']) <= 40 else result['normalized'][:37] + "..."
    tokens_str = str(result['tokens'][:3]) if len(result['tokens']) <= 3 else str(result['tokens'][:2]) + "..."
    dict_match = result['dict_match'] if result['dict_match'] else "—"
    spam = "YES" if result['symbol_spam'] else "—"
    smash = "YES" if result['keyboard_smash'] else "—"
    decision = result['final_decision']
    reason = result['reason']

    # Color coding for readability
    decision_marker = "ALLOW" if decision == "ALLOW" else "REJECT"

    status = "[OK]" if decision == "ALLOW" else "[NO]"
    print(f"{status} {raw:43} | {normalized:43} | {decision:6} | {reason}")

def run_all_tests():
    """Run comprehensive validation suite."""

    print("=" * 160)
    print("COMPREHENSIVE MODERATION VALIDATION - POLICY & TECHNICAL VERIFICATION")
    print("=" * 160)
    print()

    all_results = []

    # TEST VOCABULARY
    test_words = {
        'porn': ('restricted', 'sexual'),
        'fuck': ('restricted', 'profanity'),
        'vagina': ('non_restricted', 'anatomy'),
        'idiot': ('restricted', 'abuse'),
    }

    # ============================================================================
    print("\n" + "="*160)
    print("CATEGORY 1: EXACT MATCH")
    print("="*160)
    print("Input" + " "*39 + "| Normalized" + " "*31 + "| Decision | Reason")
    print("-"*160)

    exact_tests = [
        ("porn", "porn should be rejected"),
        ("fuck", "fuck should be rejected"),
        ("vagina", "vagina - check if in dictionary"),
        ("idiot", "idiot should be rejected"),
    ]

    for msg, note in exact_tests:
        result = trace_moderation(msg)
        print_result(result, note)
        all_results.append(('Category 1 - Exact', msg, result))

    # ============================================================================
    print("\n" + "="*160)
    print("CATEGORY 2: INSIDE SENTENCES")
    print("="*160)
    print("Input" + " "*39 + "| Normalized" + " "*31 + "| Decision | Reason")
    print("-"*160)

    sentence_tests = [
        "porn is good",
        "I like porn",
        "where can I find porn",
        "watching porn tonight",
        "fuck off",
        "you are a fucking idiot",
        "vagina hurts",
        "vagina available?",
        "That guy is an idiot",
    ]

    for msg in sentence_tests:
        result = trace_moderation(msg)
        print_result(result)
        all_results.append(('Category 2 - Sentences', msg, result))

    # ============================================================================
    print("\n" + "="*160)
    print("CATEGORY 3: CASE VARIATIONS")
    print("="*160)
    print("Input" + " "*39 + "| Normalized" + " "*31 + "| Decision | Reason")
    print("-"*160)

    case_tests = [
        "PORN", "Porn", "PoRn",
        "FUCK", "Fuck",
        "VaGiNa",
        "IDIOT", "Idiot",
    ]

    for msg in case_tests:
        result = trace_moderation(msg)
        print_result(result)
        all_results.append(('Category 3 - Case', msg, result))

    # ============================================================================
    print("\n" + "="*160)
    print("CATEGORY 4: PUNCTUATION")
    print("="*160)
    print("Input" + " "*39 + "| Normalized" + " "*31 + "| Decision | Reason")
    print("-"*160)

    punct_tests = [
        "porn.", "porn!", "porn?", "porn,", "(porn)", "porn:",
        "fuck!", "fuck?",
        "vagina?", "vagina.",
        "idiot.", "idiot!",
    ]

    for msg in punct_tests:
        result = trace_moderation(msg)
        print_result(result)
        all_results.append(('Category 4 - Punctuation', msg, result))

    # ============================================================================
    print("\n" + "="*160)
    print("CATEGORY 5: OBFUSCATION (DOTS, HYPHENS, SLASHES, UNDERSCORES)")
    print("="*160)
    print("Input" + " "*39 + "| Normalized" + " "*31 + "| Decision | Reason")
    print("-"*160)

    obfus_tests = [
        "p.o.r.n", "p-o-r-n", "p/o/r/n", "p_o_r_n",
        "f.u.c.k", "f-u-c-k", "f/u/c/k",
        "v.a.g.i.n.a", "v-a-g-i-n-a",
        "i.d.i.o.t", "i-d-i-o-t",
    ]

    for msg in obfus_tests:
        result = trace_moderation(msg)
        print_result(result)
        all_results.append(('Category 5 - Obfuscation', msg, result))

    # ============================================================================
    print("\n" + "="*160)
    print("CATEGORY 6: EXTRA SPACES")
    print("="*160)
    print("Input" + " "*39 + "| Normalized" + " "*31 + "| Decision | Reason")
    print("-"*160)

    space_tests = [
        "p o r n", "po rn", "por n",
        "f u c k", "fu ck",
        "v a g i n a",
        "i d i o t",
    ]

    for msg in space_tests:
        result = trace_moderation(msg)
        print_result(result)
        all_results.append(('Category 6 - Spaces', msg, result))

    # ============================================================================
    print("\n" + "="*160)
    print("CATEGORY 7: NUMBERS & LEETSPEAK")
    print("="*160)
    print("Input" + " "*39 + "| Normalized" + " "*31 + "| Decision | Reason")
    print("-"*160)

    leet_tests = [
        "p0rn", "pr0n", "p00n",
        "f0ck", "f*ck", "fck",
        "v4gina", "v4g1n4",
        "1d10t",
    ]

    for msg in leet_tests:
        result = trace_moderation(msg)
        print_result(result)
        all_results.append(('Category 7 - Leetspeak', msg, result))

    # ============================================================================
    print("\n" + "="*160)
    print("CATEGORY 8: MIXED SYMBOLS")
    print("="*160)
    print("Input" + " "*39 + "| Normalized" + " "*31 + "| Decision | Reason")
    print("-"*160)

    symbol_tests = [
        "@@porn##", "!!porn!!", "***porn***",
        "##fuck@@", "!!!fuck!!!",
        "@@vagina##",
        "$$idiot$$",
    ]

    for msg in symbol_tests:
        result = trace_moderation(msg)
        print_result(result)
        all_results.append(('Category 8 - Symbols', msg, result))

    # ============================================================================
    print("\n" + "="*160)
    print("CATEGORY 9: CONTEXT (RESTRICTION TOPIC IN DIFFERENT CONTEXTS)")
    print("="*160)
    print("Input" + " "*39 + "| Normalized" + " "*31 + "| Decision | Reason")
    print("-"*160)

    context_tests = [
        "Porn addiction is dangerous.",
        "Porn should be banned.",
        "Don't watch porn.",
        "Porn is harmful.",
        "Stop fucking around.",
        "Fucking idiot!",
    ]

    for msg in context_tests:
        result = trace_moderation(msg)
        print_result(result)
        all_results.append(('Category 9 - Context', msg, result))

    # ============================================================================
    print("\n" + "="*160)
    print("CATEGORY 10: SPAM / KEYBOARD SMASH / SYMBOL SPAM")
    print("="*160)
    print("Input" + " "*39 + "| Normalized" + " "*31 + "| Decision | Reason")
    print("-"*160)

    spam_tests = [
        "asdfghjkl",
        "qwertyuiop",
        "hgfkguillhiojoiiiojoihihuhnjknjb",
        "@@4444#$%^@",
        "sqs489WdAdaca46khiu",
        "asdfasdfasdfasdf",
        "!@#$%^&*()",
    ]

    for msg in spam_tests:
        result = trace_moderation(msg)
        print_result(result)
        all_results.append(('Category 10 - Spam', msg, result))

    # ============================================================================
    print("\n" + "="*160)
    print("CATEGORY 11: LANGUAGE DETECTION (NON-ENGLISH)")
    print("="*160)
    print("Input" + " "*39 + "| Normalized" + " "*31 + "| Decision | Reason")
    print("-"*160)

    lang_tests = [
        "dengutha",
        "madarchod",
        "lanjakodaka",
        "ela unnaru",
        "hello",
        "good morning",
        "where is the port",
    ]

    for msg in lang_tests:
        result = trace_moderation(msg)
        # Note: These non-English would normally be caught by Language AI (Level 2)
        print_result(result)
        all_results.append(('Category 11 - Language', msg, result))

    # ============================================================================
    print("\n" + "="*160)
    print("CATEGORY 12: HATE SPEECH & RACISM")
    print("="*160)
    print("Input" + " "*39 + "| Normalized" + " "*31 + "| Decision | Reason")
    print("-"*160)

    hate_tests = [
        "black people are idiots",
        "white people are idiots",
        "chinese are idiots",
        "all black people get lost",
        "I hate all black people",
        "Black people fuck off",
        "BLACK PEOPLE ARE IDIOTS",
        "b.l.a.c.k p.e.o.p.l.e are idiots",
    ]

    for msg in hate_tests:
        result = trace_moderation(msg)
        print_result(result)
        all_results.append(('Category 12 - Hate Speech', msg, result))

    # ============================================================================
    print("\n" + "="*160)
    print("CATEGORY 13: RELIGION-BASED DISCRIMINATION")
    print("="*160)
    print("Input" + " "*39 + "| Normalized" + " "*31 + "| Decision | Reason")
    print("-"*160)

    religion_tests = [
        "I hate Christians",
        "I hate Muslims",
        "All Hindus are stupid",
        "All Christians are idiots",
        "All Muslims should leave",
        "Christians are idiots",
        "I HATE MUSLIMS",
    ]

    for msg in religion_tests:
        result = trace_moderation(msg)
        print_result(result)
        all_results.append(('Category 13 - Religion', msg, result))

    # ============================================================================
    print("\n" + "="*160)
    print("CATEGORY 14: HARASSMENT (PERSONAL ATTACKS)")
    print("="*160)
    print("Input" + " "*39 + "| Normalized" + " "*31 + "| Decision | Reason")
    print("-"*160)

    harassment_tests = [
        "Jagadeesh is an idiot",
        "Joshan is an idiot",
        "Raj Kumar is an idiot",
        "You are an idiot",
        "Your mother is an idiot",
        "I hate you",
        "You suck",
    ]

    for msg in harassment_tests:
        result = trace_moderation(msg)
        print_result(result)
        all_results.append(('Category 14 - Harassment', msg, result))

    # ============================================================================
    print("\n" + "="*160)
    print("CATEGORY 15: REPUTATION/DEFAMATION/CRITICISM (POLICY VERIFICATION)")
    print("="*160)
    print("Input" + " "*39 + "| Normalized" + " "*31 + "| Decision | Reason")
    print("-"*160)
    print("NOTE: These tests verify POLICY, not assume they should all be blocked")
    print("-"*160)

    reputation_tests = [
        "HeyPorts is the worst platform",
        "HeyPorts is cheating people",
        "HeyPorts is a scam",
        "Don't use HeyPorts",
        "I had a bad experience with HeyPorts",
        "HeyPorts customer support is terrible",
        "I hate HeyPorts",
    ]

    for msg in reputation_tests:
        result = trace_moderation(msg)
        print_result(result)
        all_results.append(('Category 15 - Reputation', msg, result))

    # ============================================================================
    # SUMMARY REPORT
    # ============================================================================
    print("\n\n" + "=" * 160)
    print("VALIDATION SUMMARY REPORT")
    print("=" * 160)

    total_tests = len(all_results)
    rejected_tests = sum(1 for _, _, r in all_results if r['final_decision'] == 'REJECT')
    allowed_tests = sum(1 for _, _, r in all_results if r['final_decision'] == 'ALLOW')

    dict_rejections = sum(1 for _, _, r in all_results if 'restricted_word' in r['reason'])
    spam_rejections = sum(1 for _, _, r in all_results if 'spam' in r['reason'])
    smash_rejections = sum(1 for _, _, r in all_results if 'smash' in r['reason'])

    print(f"\nTotal Tests Executed: {total_tests}")
    print(f"  Rejected: {rejected_tests}")
    print(f"  Allowed: {allowed_tests}")
    print()
    print(f"Rejection Breakdown:")
    print(f"  Dictionary matches: {dict_rejections}")
    print(f"  Symbol spam: {spam_rejections}")
    print(f"  Keyboard smash: {smash_rejections}")
    print()

    # Identify categories
    categories = {}
    for cat, msg, result in all_results:
        if cat not in categories:
            categories[cat] = {'total': 0, 'rejected': 0}
        categories[cat]['total'] += 1
        if result['final_decision'] == 'REJECT':
            categories[cat]['rejected'] += 1

    print("Results by Category:")
    for cat in sorted(categories.keys()):
        stats = categories[cat]
        pct = (stats['rejected'] / stats['total'] * 100) if stats['total'] > 0 else 0
        print(f"  {cat:35} | {stats['rejected']:2}/{stats['total']:2} ({pct:5.1f}%)")

    # Identify potential issues
    print("\n" + "=" * 160)
    print("ISSUES IDENTIFIED")
    print("=" * 160)

    issues = []

    # Check for false negatives (should reject but allowed)
    false_negatives = []
    for cat, msg, result in all_results:
        # These should clearly be rejected
        if any(x in msg.lower() for x in ['porn', 'fuck', 'idiot', 'hate']):
            if result['final_decision'] == 'ALLOW' and result['dict_match'] is None:
                false_negatives.append((cat, msg, result['reason']))

    if false_negatives:
        print("\nFALSE NEGATIVES (Should reject but allowed):")
        for cat, msg, reason in false_negatives:
            print(f"  - {cat}: '{msg}' (Reason: {reason})")
            issues.append(('False Negative', msg))
    else:
        print("\nFALSE NEGATIVES: None detected in dictionary-based checks")

    # Check language detection (not caught by dictionary)
    print("\nLANGUAGE DETECTION GAPS:")
    non_english = ['dengutha', 'madarchod', 'lanjakodaka', 'ela unnaru']
    for msg in non_english:
        for _, test_msg, result in all_results:
            if test_msg == msg and result['final_decision'] == 'ALLOW':
                print(f"  - '{msg}' allowed (Would require Level 2 Language AI)")
                issues.append(('Language Detection', msg))
                break

    # Check symbol spam
    print("\nSYMBOL SPAM DETECTION:")
    symbol_spam_tests = ['@@4444#$%^@', '@@porn##', '!!porn!!']
    for msg in symbol_spam_tests:
        for _, test_msg, result in all_results:
            if test_msg == msg:
                if result['final_decision'] == 'REJECT' and 'spam' in result['reason']:
                    print(f"  [OK] '{msg}' correctly detected as spam")
                else:
                    print(f"  [NO] '{msg}' NOT detected as spam")
                    issues.append(('Symbol Spam Detection', msg))
                break

    # Check obfuscation
    print("\nOBFUSCATION DETECTION:")
    obfus_tested = ['p.o.r.n', 'f.u.c.k', 'f-u-c-k', 'i-d-i-o-t']
    obfus_working = 0
    obfus_failing = 0
    for target_word in obfus_tested:
        for _, test_msg, result in all_results:
            if test_msg == target_word:
                if result['final_decision'] == 'REJECT' and result['dict_match']:
                    print(f"  [OK] '{target_word}' -> '{result['dict_match']}' matched")
                    obfus_working += 1
                else:
                    print(f"  [NO] '{target_word}' NOT detected")
                    obfus_failing += 1
                    issues.append(('Obfuscation', target_word))
                break

    print(f"\n  Obfuscation Detection: {obfus_working}/{len(obfus_tested)} working")

    # ========================================================================
    print("\n" + "=" * 160)
    print("POLICY VERIFICATION - REPUTATION/DEFAMATION")
    print("=" * 160)
    print("\nThese messages test policy, not implementation:")
    print("-" * 160)

    rep_messages = [
        "HeyPorts is the worst platform",
        "HeyPorts customer support is terrible",
        "I had a bad experience with HeyPorts",
    ]

    for msg in rep_messages:
        for _, test_msg, result in all_results:
            if test_msg == msg:
                print(f"\n'{msg}'")
                print(f"  Decision: {result['final_decision']}")
                print(f"  Reason: {result['reason']}")
                if result['final_decision'] == 'ALLOW':
                    print(f"  [OK] CORRECT: Criticism allowed by policy")
                elif result['final_decision'] == 'REJECT':
                    print(f"  [NO] ISSUE: Legitimate criticism blocked")
                    issues.append(('Policy', f'Blocking criticism: {msg}'))
                break

    # ========================================================================
    print("\n\n" + "=" * 160)
    print("FINAL ASSESSMENT")
    print("=" * 160)

    print(f"\nTotal Issues Found: {len(issues)}")

    if issues:
        print("\nIssue Breakdown:")
        issue_types = {}
        for issue_type, msg in issues:
            if issue_type not in issue_types:
                issue_types[issue_type] = []
            issue_types[issue_type].append(msg)

        for issue_type in sorted(issue_types.keys()):
            print(f"\n{issue_type}:")
            for msg in issue_types[issue_type]:
                print(f"  - {msg}")

    print("\n" + "=" * 160)
    print("PRODUCTION READINESS ASSESSMENT")
    print("=" * 160)

    # Calculate confidence
    expected_working = 0
    for cat, msg, result in all_results:
        # Things that should definitely work
        if any(x in cat.lower() for x in ['exact', 'sentence', 'case', 'punctuation']):
            if result['final_decision'] == 'REJECT' and result['dict_match']:
                expected_working += 1

    expected_total = sum(1 for cat, msg, result in all_results
                        if any(x in cat.lower() for x in ['exact', 'sentence', 'case', 'punctuation']))

    confidence = (expected_working / expected_total * 100) if expected_total > 0 else 0

    print(f"\nCore functionality (Exact, Sentences, Case, Punctuation): {confidence:.1f}%")

    if confidence >= 90:
        print("Status: READY for production (core features working)")
    elif confidence >= 70:
        print("Status: PARTIAL - needs review of edge cases")
    else:
        print("Status: NOT READY - significant issues remain")

    print("\nRemaining work:")
    print("  - Language detection: Requires Level 2 Language AI integration")
    print("  - Keyboard smash: Complex entropy-based detection")
    print("  - Advanced harassment: Requires context-aware AI")

    return all_results, categories, issues

if __name__ == "__main__":
    results, categories, issues = run_all_tests()
