"""Text normalization for chat moderation matching.

Normalization pipeline:
1. Lowercase
2. Strip whitespace
3. Collapse multiple spaces
4. Remove zero-width/control chars
5. Collapse character runs (aaa→aa)
6. Collapse multiple punctuation (!!! → !)
7. Remove intra-word punctuation (s.e.x → sex)
8. Remove spaced-out single letters (p o r n → porn)
9. Apply ONLY numeric/symbolic leet substitutions (0→o, 1→i, not !→i or @→a)
10. Strip non-word characters except apostrophes
11. Final space collapse
"""
import re
import unicodedata

_LEET_TABLE = {
    '4': 'a',
    '3': 'e',
    '1': 'i',
    '0': 'o',
    '5': 's',
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

    def remove_excessive_spaces(match):
        token = match.group(0)
        letters = sum(1 for c in token if c.isalpha())
        spaces = sum(1 for c in token if c == ' ')
        if letters > 2 and spaces >= letters - 1:
            return token.replace(' ', '')
        return token
    result = re.sub(r'[a-z](?:\s[a-z])+', remove_excessive_spaces, result)

    result = ''.join(_LEET_TABLE.get(c, c) for c in result)

    result = re.sub(r'[^a-z0-9\s\']', '', result)

    result = re.sub(r'\s+', ' ', result).strip()

    return result
