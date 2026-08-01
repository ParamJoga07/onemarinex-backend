"""Text normalization for chat moderation matching.

All 11 rules applied in order. Normalized text is for matching only; the original
raw text is what gets stored and broadcast.
"""
import re
import unicodedata

_LEET_TABLE = {
    '@': 'a', '4': 'a',
    '3': 'e',
    '1': 'i', '!': 'i',
    '0': 'o',
    '5': 's', '$': 's',
    '7': 't',
    'z': 's',
}

_CHAR_RUN_PATTERN = re.compile(r'(.)\1{2,}')


def normalize(text: str) -> str:
    """Normalize text for matching. Returns normalized string."""
    if not text:
        return ""

    result = text

    result = result.lower()

    result = result.strip()

    result = re.sub(r'\s+', ' ', result)

    result = ''.join(
        c for c in result
        if unicodedata.category(c) not in ('Cf', 'Cc', 'Cn')
    )

    result = _CHAR_RUN_PATTERN.sub(r'\1\1', result)

    result = re.sub(r'([.!?]){2,}', r'\1', result)

    while re.search(r'[a-z][._\-/\\*!]+[a-z]', result):
        result = re.sub(r'([a-z])[._\-/\\*!]+([a-z])', r'\1\2', result)

    result = ''.join(_LEET_TABLE.get(c, c) for c in result)

    result = re.sub(r'[^a-z0-9\s.!?\'\"-]', '', result)

    result = re.sub(r'\s+', ' ', result).strip()

    return result
