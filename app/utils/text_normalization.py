"""Complete text normalization pipeline for moderation.

Normalization pipeline (in order):
1. Input validation (empty, length, charset)
2. Unicode NFKD (compatible decomposition)
3. Combine mark removal (accents)
4. Lowercase
5. Strip/collapse whitespace
6. Remove control/format characters
7. Collapse character runs (aaa → aa)
8. Collapse multiple punctuation (!!! → !)
9. Remove intra-word punctuation (s.e.x → sex)
10. Remove spaced-out letters (p o r n → porn)
11. Leetspeak normalization (numeric only)
12. Strip emoji and symbols (keep ASCII + letters)
13. Final whitespace collapse
"""

import re
import unicodedata
from typing import Tuple, Optional

_LEET_TABLE = {
    '0': 'o',
    '1': 'i',
    '3': 'e',
    '4': 'a',
    '5': 's',
    '7': 't',
    '8': 'b',
    '9': 'g',
}

_CHAR_RUN_PATTERN = re.compile(r'(.)\1{2,}')


def validate_input(text: str) -> Tuple[Optional[str], Optional[str]]:
    """Validate input before normalization.

    Returns: (text, error_code) or (None, error_code) if invalid
    """
    if not text:
        return None, "empty_message"

    if len(text) > 5000:
        return None, "too_long"

    return text, None


def normalize(text: str) -> str:
    """Complete normalization pipeline.

    Returns normalized text suitable for dictionary matching.
    Original text is preserved separately for logging.
    """
    if not text:
        return ""

    result = text

    # 1. Unicode NFKD (compatible decomposition)
    # Converts 𝐩 (mathematical bold) → p
    result = unicodedata.normalize('NFKD', result)

    # 2. Remove combining marks (accents, diacritics)
    result = ''.join(
        c for c in result
        if unicodedata.category(c) != 'Mn'
    )

    # 3. Lowercase
    result = result.lower()

    # 4. Strip leading/trailing whitespace
    result = result.strip()

    # 5. Collapse multiple spaces to single space
    result = re.sub(r'\s+', ' ', result)

    # 6. Remove control/format/unassigned characters
    # Keep: letters, digits, spaces (U+0020), common punctuation
    result = ''.join(
        c for c in result
        if unicodedata.category(c) not in ('Cf', 'Cc', 'Cn') or c == ' '
    )

    # 7. Collapse character runs (aaa → aa)
    result = _CHAR_RUN_PATTERN.sub(r'\1\1', result)

    # 8. Collapse multiple punctuation (!!! → !)
    result = re.sub(r'([.!?]){2,}', r'\1', result)

    # 9. Remove intra-word obfuscation symbols (p##rn → prn, p@@rn → prn, etc.)
    # Remove non-alphanumeric chars between letter pairs
    # Extended character set to catch: # @ * _ + = ~ | \ / $ % ^ & etc.
    while re.search(r'[a-z][#@*_+=~|\\/$%^&\-\.!]+[a-z]', result):
        result = re.sub(r'([a-z])[#@*_+=~|\\/$%^&\-\.!]+([a-z])', r'\1\2', result)

    # 10. Remove spaced-out letters (p o r n → porn, s e x → sex)
    # Pattern: letter space letter space... including repeated letters with spaces
    def remove_letter_spaces(match):
        token = match.group(0)
        letters = sum(1 for c in token if c.isalpha())
        spaces = sum(1 for c in token if c == ' ')
        # If heavily spaced (spaces >= letters - 1), remove spaces
        # Catch patterns like: s e, e x, p o (min 2 letters with spaces)
        if spaces >= letters - 1 and letters >= 2:
            return token.replace(' ', '')
        return token

    result = re.sub(r'[a-z](?:\s[a-z])+', remove_letter_spaces, result)

    # 11. Leetspeak normalization (numeric ONLY)
    result = ''.join(_LEET_TABLE.get(c, c) for c in result)

    # 12. Remove emoji and non-ASCII symbols
    # Keep: a-z, 0-9, spaces, apostrophes only
    result = re.sub(r'[^a-z0-9\s\']', '', result)

    # 13. Collapse excessively repeated letters (seeeex → sex, aaaa → a)
    # After removing symbols, any 2+ identical consecutive letters likely indicate obfuscation
    result = re.sub(r'([a-z])\1+', r'\1', result)

    # 14. Final whitespace collapse and strip
    result = re.sub(r'\s+', ' ', result).strip()

    return result


def detect_repeated_characters(text: str) -> bool:
    """Detect obvious spam patterns with repeated characters and keyboard smash.

    Examples:
    - aaaaaaaaaaaaaaaaaaaa (repeated letter spam)
    - pooooooorn (6+ repeated chars in word)
    - asdfghjkl (keyboard row)
    - 12345678 (number sequence)
    - shshrjrjjdkddkjd (random key smash)
    - 20@@Fhbjsbaacmagd (mixed random chars)
    """
    if len(text) < 3:
        return False

    # 1. Detect 4+ consecutive identical characters (aaa, oooo, etc.)
    if re.search(r'(.)\1{3,}', text):
        return True

    # 2. Detect common keyboard patterns
    keyboard_patterns = [
        'asdfghjkl',
        'qwertyuiop',
        'zxcvbnm',
        '12345678',
        '1234567890',
    ]

    text_lower = text.lower()
    for pattern in keyboard_patterns:
        if pattern in text_lower:
            return True

    # 3. Detect keyboard smash: random consonant clusters and excessive repeated chars
    # Pattern: consonant cluster spam like "jdkddkjd" or "rjrjjdk"
    if _is_keyboard_smash(text_lower):
        return True

    return False


def _is_keyboard_smash(text: str) -> bool:
    """Detect keyboard smash by analyzing randomness and entropy.

    Characteristics of keyboard smash:
    - High ratio of consonant clusters (3+ consonants in a row)
    - Excessive character repetition (same char appears 3+ times non-contiguously)
    - Low vowel ratio (< 15% for alphanumeric text)
    - No real word patterns
    - High entropy (random character distribution)
    """
    if len(text) < 5:
        return False

    vowels = 'aeiou'
    consonants = 'bcdfghjklmnpqrstvwxyz'

    # Count letters only (not numbers)
    letter_chars = [c for c in text if c.isalpha()]
    letter_text = ''.join(letter_chars)

    # 1. Check vowel ratio among letters - legitimate text has 30%+ vowels
    if letter_text and len(letter_text) >= 4:
        vowel_count = sum(1 for c in letter_text if c in vowels)
        vowel_ratio = vowel_count / len(letter_text)
        if vowel_ratio < 0.2:  # Low vowel ratio in letter-only text is suspicious
            return True

    # 2. Check for excessive consonant clusters (3+ consonants in a row)
    consonant_clusters = len(re.findall(r'[bcdfghjklmnpqrstvwxyz]{3,}', text))
    if consonant_clusters >= 2:  # Multiple weird consonant clusters
        return True

    # 3. Check for character distribution randomness
    # Legitimate text has predictable char distribution; smash has highly varied
    if _has_high_entropy(text):
        return True

    return False


def _has_high_entropy(text: str) -> bool:
    """Detect random character distribution (entropy).

    Keyboard smash has high entropy (many different chars appearing unpredictably).
    Legitimate text has lower entropy (predictable word patterns).
    """
    if len(text) < 5:
        return False

    # Count character frequency
    char_freq = {}
    for c in text:
        if c.isalnum():  # Only count alphanumeric
            char_freq[c] = char_freq.get(c, 0) + 1

    if not char_freq:
        return False

    # Calculate Shannon entropy
    total = sum(char_freq.values())
    entropy = 0
    for count in char_freq.values():
        if count > 0:
            p = count / total
            entropy -= p * (p if p == 0 else __import__('math').log2(p))

    # Legitimate text entropy: 3.5-4.5
    # Random spam entropy: 3.8+
    # If we have 4+ distinct chars and high entropy, it's likely smash
    return entropy > 3.65 and len(char_freq) >= 4


def is_excessive_non_ascii(text: str) -> bool:
    """Detect messages that are mostly non-ASCII (likely spam)."""
    if len(text) < 5:
        return False

    ascii_count = sum(1 for c in text if ord(c) < 128)
    ascii_ratio = ascii_count / len(text)

    # If < 20% ASCII, likely spam
    return ascii_ratio < 0.2
