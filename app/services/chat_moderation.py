"""Chat message moderation pipeline orchestrator.

Implements the three-level moderation pipeline:
- Level 0: Text normalization
- Level 1: Deterministic checks (no AI)
- Level 2: Routing and AI-based checks

Exports: ModerationResult, moderate_message()
"""
import logging
import re
from collections import deque
from datetime import datetime, timedelta
from typing import Optional, Dict, Set
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.utils.text_normalization import normalize, normalize_for_dictionary_matching
from app.services.moderation_ai import check_language, check_context

logger = logging.getLogger("heyports.chat_moderation")

_flood_deques: Dict[tuple, deque] = {}
_duplicate_cache: Dict[tuple, tuple] = {}
_dictionary_cache = None
_phrase_regex = None
_cache_loaded_at = None
_CACHE_TTL_SECONDS = 60


class ModerationResult(BaseModel):
    rejected: bool
    code: Optional[str] = None
    message: Optional[str] = None
    reason_code: Optional[str] = None
    rejected_by: Optional[str] = None
    matched_term: Optional[str] = None
    ai_route: Optional[str] = None
    ai_model: Optional[str] = None
    ai_latency_ms: Optional[int] = None
    ai_input_tokens: Optional[int] = None
    ai_output_tokens: Optional[int] = None


_PHONE_REGEX = re.compile(r'(\+\d{1,3}[-.\s]?)?\(?([0-9]{1,4})\)?[-.\s]?([0-9]{1,4})[-.\s]?([0-9]{1,9})')
_EMAIL_REGEX = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')
_URL_REGEX = re.compile(r'https?://[^\s]+|www\.[^\s]+')
_UPI_REGEX = re.compile(r'\b[a-zA-Z0-9._-]+@[a-zA-Z]{3,}\b')
_CARD_REGEX = re.compile(r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b|\bcard\b')
_IFSC_REGEX = re.compile(r'\b[A-Z]{4}0[A-Z0-9]{6}\b')
_HANDLE_REGEX = re.compile(r'@[a-zA-Z0-9_]+')

_CONTEXTUAL_TRIGGERS = {
    'arrange', 'arrangement', 'something special', 'privately', 'private',
    'green stuff', 'anything special', 'help me out', 'discrete',
    'under table', 'cash only', 'no record', 'off books',
}


def _ensure_settings(db: Session):
    """Ensure settings row exists, create if missing."""
    from app.db.models.chat_moderation_setting import ChatModerationSetting
    settings = db.query(ChatModerationSetting).filter(ChatModerationSetting.id == 1).first()
    if not settings:
        settings = ChatModerationSetting(id=1)
        db.add(settings)
        db.commit()
    return settings


def reload_restricted_words(db: Session) -> None:
    """Reload the in-memory dictionary from the database. Call after add/delete/import."""
    from app.db.models.chat_restricted_word import ChatRestrictedWord
    global _dictionary_cache, _phrase_regex, _cache_loaded_at

    words = db.query(ChatRestrictedWord).filter(ChatRestrictedWord.is_active).all()

    single_words = set()
    phrases = []

    for w in words:
        normalized = w.word.lower().strip()
        if ' ' in normalized:
            phrases.append(re.escape(normalized))
        else:
            single_words.add(normalized)

    _dictionary_cache = single_words
    if phrases:
        _phrase_regex = re.compile(r'\b(' + '|'.join(phrases) + r')\b')
    else:
        _phrase_regex = None

    _cache_loaded_at = datetime.utcnow()
    logger.info("Restricted words dictionary reloaded: %d single words, %d phrases", len(single_words), len(phrases))


def _get_cached_dictionary(db: Session) -> tuple:
    """Return (single_words_set, phrase_regex) with TTL refresh."""
    global _dictionary_cache, _phrase_regex, _cache_loaded_at

    # Check if cache needs refresh
    needs_refresh = (
        _dictionary_cache is None or
        _cache_loaded_at is None or
        (datetime.utcnow() - _cache_loaded_at).total_seconds() > _CACHE_TTL_SECONDS
    )

    if needs_refresh:
        reload_restricted_words(db)

    result_dict = _dictionary_cache or set()
    return result_dict, _phrase_regex


async def moderate_message(
    db: Session,
    user_id: int,
    port_id: int,
    raw_text: str,
) -> ModerationResult:
    """Execute the moderation pipeline: deterministic → restricted words → AI contextual.

    Policy: Any restricted dictionary word is an immediate, non-negotiable rejection.
    AI is only called for contextual violations if no dictionary match exists.
    Fail-closed: when in doubt, reject.
    """
    settings = _ensure_settings(db)
    normalized = normalize(raw_text)

    if not normalized:
        result = ModerationResult(rejected=True, code="empty", reason_code="empty", rejected_by="level_1")
        return result

    if len(normalized) > settings.max_message_length:
        result = ModerationResult(rejected=True, code="too_long", reason_code="too_long", rejected_by="level_1")
        return result

    if _check_flood(user_id, port_id, settings):
        result = ModerationResult(rejected=True, code="rate_limited", reason_code="rate_limited", rejected_by="level_1")
        return result

    if _check_duplicate(user_id, port_id, normalized, settings):
        result = ModerationResult(rejected=True, code="duplicate", reason_code="duplicate", rejected_by="level_1")
        return result

    if _check_contact_info(normalized):
        result = ModerationResult(rejected=True, code="contact_info", reason_code="contact_info", rejected_by="level_1")
        return result

    if settings.block_payment_info and _check_payment_info(normalized):
        result = ModerationResult(rejected=True, code="payment_info", reason_code="payment_info", rejected_by="level_1")
        return result

    if settings.block_external_links and _check_external_links(normalized):
        result = ModerationResult(rejected=True, code="external_link", reason_code="external_link", rejected_by="level_1")
        return result

    if _check_raw_spam(raw_text):
        result = ModerationResult(rejected=True, code="spam", reason_code="spam", rejected_by="level_1")
        return result

    if _check_spam(normalized):
        result = ModerationResult(rejected=True, code="spam", reason_code="spam", rejected_by="level_1")
        return result

    if _check_charset(normalized):
        result = ModerationResult(rejected=True, code="charset", reason_code="charset", rejected_by="level_1")
        return result

    single_words, phrase_regex = _get_cached_dictionary(db)
    normalized_for_dict = normalize_for_dictionary_matching(raw_text)
    matched_term = _check_dictionary(normalized_for_dict, single_words, phrase_regex)

    if matched_term:
        result = ModerationResult(
            rejected=True,
            code="restricted_word",
            reason_code="restricted_word",
            rejected_by="level_1",
            matched_term=matched_term
        )
        return result

    if settings.moderation_ai_enabled or settings.language_ai_enabled:
        ai_result = await _check_contextual_violations(normalized, settings)
        if ai_result:
            return ai_result

    result = ModerationResult(rejected=False, rejected_by="backend")
    return result


async def _check_contextual_violations(normalized: str, settings, trace: dict = None) -> Optional[ModerationResult]:
    """Check for contextual violations that require AI understanding.

    This is only called when there are NO restricted dictionary matches.

    AI Invocation Order (optimized for cost):
    1. Language AI first - Reject immediately if non-English
    2. Moderation AI only if Language AI returns ENGLISH

    Language AI detects:
    - Non-English language messages

    Moderation AI detects:
    - Threats and violence
    - Harassment and bullying
    - Discrimination and hate speech
    - Encouragement of self-harm
    - Defamation
    - Illegal activity
    - Bribery/corruption
    - Drug solicitation
    - Prostitution solicitation
    - Grooming and coercion
    """
    if settings.language_ai_enabled:
        verdict = await check_language(normalized)
        logger.debug(f"Language check: {verdict.result}")

        if verdict.result == "LANGUAGE":
            logger.info("Non-English message detected - rejecting without Moderation AI call")
            return ModerationResult(
                rejected=True,
                code="language_violation",
                reason_code="language_violation",
                rejected_by="language_ai",
                ai_route="language",
                ai_model="claude-haiku-4-5"
            )

    if settings.moderation_ai_enabled:
        verdict = await check_context(normalized)
        logger.debug(f"Moderation AI verdict: {verdict.result}")

        if verdict.result in ("HARASSMENT", "ABUSE"):
            return ModerationResult(
                rejected=True,
                code="guidelines_violation",
                reason_code="guidelines_violation",
                rejected_by="moderation_ai",
                ai_route="context",
                ai_model="claude-haiku-4-5"
            )

    return None


def _check_flood(user_id: int, port_id: int, settings) -> bool:
    """Check if user exceeded rate limit (5 messages in 10 seconds per port)."""
    now = datetime.utcnow().timestamp()
    key = (user_id, port_id)

    if key not in _flood_deques:
        _flood_deques[key] = deque()

    deq = _flood_deques[key]

    while deq and deq[0] < now - settings.rate_limit_window_seconds:
        deq.popleft()

    if len(deq) >= settings.rate_limit_count:
        return True

    deq.append(now)
    return False


def _check_duplicate(user_id: int, port_id: int, normalized: str, settings) -> bool:
    """Check if message is a duplicate within window per port."""
    now = datetime.utcnow().timestamp()
    key = (user_id, port_id)
    msg_hash = hash(normalized)

    if key in _duplicate_cache:
        prev_hash, prev_ts = _duplicate_cache[key]
        if now - prev_ts < settings.duplicate_window_seconds and prev_hash == msg_hash:
            return True

    _duplicate_cache[key] = (msg_hash, now)
    return False


def _check_contact_info(normalized: str) -> bool:
    """Check for phone/email/handle patterns."""
    return bool(_PHONE_REGEX.search(normalized) or
                _EMAIL_REGEX.search(normalized) or
                _HANDLE_REGEX.search(normalized))


def _check_payment_info(normalized: str) -> bool:
    """Check for payment-related patterns."""
    return bool(_UPI_REGEX.search(normalized) or
                _CARD_REGEX.search(normalized) or
                _IFSC_REGEX.search(normalized))


def _check_external_links(normalized: str) -> bool:
    """Check for URLs."""
    return bool(_URL_REGEX.search(normalized))


def _check_spam(normalized: str) -> bool:
    """Check spam heuristics: char-run ratio, repeated-token ratio."""
    if not normalized:
        return False

    non_space_len = sum(1 for c in normalized if c != ' ')
    if non_space_len < 3:
        return False

    char_runs = sum(1 for c in normalized if c.isalpha())
    if non_space_len > 0 and (char_runs / non_space_len) < 0.3:
        return True

    repeated_word_count = len(normalized.split())
    unique_words = len(set(normalized.split()))
    if repeated_word_count > 1 and (unique_words / repeated_word_count) < 0.3:
        return True

    return False


def _check_raw_spam(raw_text: str) -> bool:
    """Check raw text for obvious spam patterns before normalization.

    Detects:
    - Very low letter ratio (mostly symbols)
    - Keyboard smash patterns (repeated chars, consonant clusters, high entropy)
    - Random character sequences
    """
    if not raw_text or len(raw_text) < 3:
        return False

    from app.utils.text_normalization import detect_repeated_characters

    letters = sum(1 for c in raw_text if c.isalpha())
    total = len(raw_text)

    if total > 0 and (letters / total) < 0.2:
        return True

    if detect_repeated_characters(raw_text):
        return True

    return False


def _check_dictionary(normalized: str, single_words: Set[str], phrase_regex: Optional[re.Pattern]) -> Optional[str]:
    """Check against restricted words and phrases."""
    tokens = normalized.split()

    for token in tokens:
        clean_token = re.sub(r'[^a-z0-9]', '', token)
        in_dict = clean_token in single_words if single_words else False
        if clean_token and in_dict:
            return clean_token

    if phrase_regex:
        match = phrase_regex.search(normalized)
        if match:
            return match.group(1)

    return None


def _check_charset(normalized: str) -> bool:
    """Check for keyboard-smash and gibberish (low alphanumeric ratio, random patterns)."""
    if not normalized:
        return False

    from app.utils.text_normalization import detect_repeated_characters

    non_space = sum(1 for c in normalized if c != ' ')
    alpha = sum(1 for c in normalized if c.isalpha())

    if non_space > 0:
        ratio = alpha / non_space
        if ratio < 0.3:
            return True

    if detect_repeated_characters(normalized):
        return True

    return False
