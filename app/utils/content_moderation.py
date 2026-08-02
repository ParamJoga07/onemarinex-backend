import re
import time
import functools
import unicodedata
from typing import Tuple, Dict, List
from app.core.config import settings

# --- Tier 0: In-Memory Sliding Window Rate Limiter ---
class ChatRateLimiter:
    def __init__(self):
        # Maps user_id -> List of timestamps
        self._user_timestamps: Dict[int, List[float]] = {}

    def is_rate_limited(self, user_id: int, max_messages: int = None, window_seconds: int = None) -> bool:
        if max_messages is None:
            max_messages = getattr(settings, "CHAT_RATE_LIMIT_MAX", 5)
        if window_seconds is None:
            window_seconds = getattr(settings, "CHAT_RATE_LIMIT_SECONDS", 10)

        now = time.time()
        cutoff = now - window_seconds

        timestamps = self._user_timestamps.get(user_id, [])
        valid_timestamps = [t for t in timestamps if t > cutoff]

        if len(valid_timestamps) >= max_messages:
            self._user_timestamps[user_id] = valid_timestamps
            return True

        valid_timestamps.append(now)
        self._user_timestamps[user_id] = valid_timestamps
        return False

rate_limiter = ChatRateLimiter()

# Regex patterns for PII & URLs
EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", re.IGNORECASE)
PHONE_REGEX = re.compile(r"(\+?\d{1,4}[-.\s]?)?(\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}", re.IGNORECASE)
URL_REGEX = re.compile(r"(https?://|www\.|[a-zA-Z0-9-]+\.(com|org|net|io|co|in|app|dev|me|info|biz))", re.IGNORECASE)

BASE_BAD_WORDS = {
    "fuck", "fucking", "fucked", "fucker", "fuckers", "fuckyou", "fck", "fuk",
    "shit", "shitting", "shitted", "shite", "sh1t",
    "ass", "asses", "asshole", "assholes", "arse", "arsehole", "@ss",
    "bitch", "bitches", "bitching", "sonofabitch", "b!tch",
    "bastard", "bastards",
    "damn", "dammit",
    "cock", "cocks", "cocksucker", "dick", "dicks", "dickhead", "d!ck",
    "piss", "pissing", "pissed",
    "cunt", "cunts", "c*nt",
    "whore", "whores", "w&ore",
    "slut", "sluts",
    "motherfucker", "motherfucking", "mf",
    "nigger", "nigga", "niggas", "n!gger",
    "fag", "faggot", "faggots",
    "retard", "retarded",
    "bollocks", "twat", "wanker",
    "prostitute", "prostitution", "trafficking", "escort"
}

def get_all_bad_words() -> set:
    extra = set(getattr(settings, "CHAT_EXTRA_BLOCKED_WORDS", []))
    return BASE_BAD_WORDS.union(extra)

REGEX_PATTERNS = [
    re.compile(r"\bf+[u*x@k01345!]+c*k[a-z]*\b", re.IGNORECASE),
    re.compile(r"\bs+[h#*]+[i!1*]+t+[a-z]*\b", re.IGNORECASE),
    re.compile(r"\ba+[s$*]{2,}(h[o0]le)?\b", re.IGNORECASE),
    re.compile(r"\bb+[i!1*]+t+c+h+[a-z]*\b", re.IGNORECASE),
    re.compile(r"\bd+[i!1*]+c+k+[a-z]*\b", re.IGNORECASE),
    re.compile(r"\bc+[u*!1]+n+t+[a-z]*\b", re.IGNORECASE),
    re.compile(r"\bm+f+u+c+k+[a-z]*\b", re.IGNORECASE),
    re.compile(r"\bn+[i!1*]+g+g+[a-z]*\b", re.IGNORECASE),
    re.compile(r"\bf+[a@!1]+g+[ot]*\b", re.IGNORECASE),
]

BENIGN_PREFIXES = (
    "hi", "hello", "hey", "good morning", "good evening", "good afternoon",
    "ok", "okay", "thanks", "thank you", "yes", "no", "sure", "got it",
    "where", "when", "how", "what", "which", "cab", "vessel", "port", "gate",
    "pier", "driver", "agent", "crew", "sea", "ship", "boat", "hotel",
    "restaurant", "pub", "bar", "food", "taxi", "bus", "weather", "help"
)


def normalize_leetspeak(text: str) -> str:
    """Normalize common leetspeak substitutions to standard alphabetic characters."""
    leet_map = {
        '@': 'a', '4': 'a',
        '8': 'b',
        '3': 'e',
        '1': 'i', '!': 'i', '|': 'i',
        '0': 'o',
        '$': 's', '5': 's',
        '7': 't', '+': 't'
    }
    chars = [leet_map.get(ch, ch) for ch in text.lower()]
    return "".join(chars)


def check_tier0_prechecks(text: str, user_id: int = 0) -> Tuple[bool, str]:
    """
    Tier 0: Pre-checks (Rate limit, length, PII, URLs).
    Returns (is_blocked: bool, reason: str).
    """
    if not text or not text.strip():
        return True, "empty_message"

    max_len = getattr(settings, "CHAT_MAX_MESSAGE_LENGTH", 1000)
    if len(text) > max_len:
        return True, "oversized_message"

    if user_id > 0:
        if rate_limiter.is_rate_limited(user_id):
            return True, "rate_limited"

    # PII Check (Phone, Email)
    if getattr(settings, "CHAT_BLOCK_PII", True):
        if EMAIL_REGEX.search(text):
            return True, "contains_email"
        digits_only = "".join(ch for ch in text if ch.isdigit())
        if len(digits_only) >= 7 and PHONE_REGEX.search(text):
            return True, "contains_phone"

    # URL Check
    if getattr(settings, "CHAT_BLOCK_URLS", True):
        if URL_REGEX.search(text):
            return True, "contains_url"

    return False, ""


@functools.lru_cache(maxsize=2048)
def check_tier1_local(text: str) -> bool:
    """Tier 1: Fast local check ($0 cost). Returns True if message contains abusive language."""
    if not text or not text.strip():
        return False

    raw_lower = text.lower()
    normalized = normalize_leetspeak(text)
    bad_words = get_all_bad_words()

    words = raw_lower.split() + normalized.split()
    for w in words:
        cleaned = w.strip(".,!?;:'\"()[]{}<>@#$%^&*-_+=~`|/\\")
        if cleaned in bad_words:
            return True

    for pattern in REGEX_PATTERNS:
        if pattern.search(raw_lower) or pattern.search(normalized):
            return True

    return False


def is_emoji_only(text: str) -> bool:
    """Check if message consists exclusively of emojis or whitespace."""
    stripped = text.strip()
    if not stripped:
        return False
    for ch in stripped:
        if ch.isspace():
            continue
        cat = unicodedata.category(ch)
        if not (cat.startswith("S") or cat.startswith("P")):
            return False
    return True


def is_benign_candidate(text: str) -> bool:
    """Tier 2: Check if message is a simple benign phrase or emoji that can skip AI checks."""
    cleaned = text.strip().lower()

    if is_emoji_only(text):
        return True

    if len(cleaned) <= 40:
        if any(cleaned.startswith(prefix) for prefix in BENIGN_PREFIXES):
            return True

    return False
