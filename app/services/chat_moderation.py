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

from app.utils.text_normalization import normalize
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
        normalized = w.word.lower()
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
        logger.info("DEBUG: Reloading restricted words dictionary")
        reload_restricted_words(db)

    result_dict = _dictionary_cache or set()
    logger.info(f"DEBUG: Returning dictionary with {len(result_dict)} words")
    return result_dict, _phrase_regex


async def moderate_message(
    db: Session,
    user_id: int,
    port_id: int,
    raw_text: str,
) -> ModerationResult:
    """Execute the three-level moderation pipeline.

    Returns a ModerationResult with rejection decision and audit fields.
    Never raises; failures follow fail_closed policy.
    """
    settings = _ensure_settings(db)
    normalized = normalize(raw_text)

    result = ModerationResult(rejected=False)

    if not normalized:
        result.rejected = True
        result.code = "empty"
        result.reason_code = "empty"
        result.rejected_by = "level_1"
        return result

    if len(normalized) > settings.max_message_length:
        result.rejected = True
        result.code = "too_long"
        result.reason_code = "too_long"
        result.rejected_by = "level_1"
        return result

    if _check_flood(user_id, port_id, settings):
        result.rejected = True
        result.code = "rate_limited"
        result.reason_code = "rate_limited"
        result.rejected_by = "level_1"
        return result

    if _check_duplicate(user_id, port_id, normalized, settings):
        result.rejected = True
        result.code = "duplicate"
        result.reason_code = "duplicate"
        result.rejected_by = "level_1"
        return result

    if _check_contact_info(normalized):
        result.rejected = True
        result.code = "contact_info"
        result.reason_code = "contact_info"
        result.rejected_by = "level_1"
        return result

    if settings.block_payment_info and _check_payment_info(normalized):
        result.rejected = True
        result.code = "payment_info"
        result.reason_code = "payment_info"
        result.rejected_by = "level_1"
        return result

    if settings.block_external_links and _check_external_links(normalized):
        result.rejected = True
        result.code = "external_link"
        result.reason_code = "external_link"
        result.rejected_by = "level_1"
        return result

    if _check_raw_spam(raw_text):
        result.rejected = True
        result.code = "spam"
        result.reason_code = "spam"
        result.rejected_by = "level_1"
        return result

    if _check_spam(normalized):
        result.rejected = True
        result.code = "spam"
        result.reason_code = "spam"
        result.rejected_by = "level_1"
        return result

    single_words, phrase_regex = _get_cached_dictionary(db)
    logger.info(f"DEBUG: Dictionary loaded - single_words count: {len(single_words) if single_words else 0}")

    matched_term = _check_dictionary(normalized, single_words, phrase_regex)
    logger.info(f"DEBUG: Dictionary check result - matched_term: {matched_term}, tokens: {normalized.split()}")

    if _check_charset(normalized):
        result.rejected = True
        result.code = "charset"
        result.reason_code = "charset"
        result.rejected_by = "level_1"
        return result

    if not settings.language_ai_enabled and not settings.moderation_ai_enabled:
        if matched_term:
            result.rejected = True
            result.code = "restricted_word"
            result.reason_code = "restricted_word"
            result.rejected_by = "level_1"
            result.matched_term = matched_term
        else:
            result.rejected = False
            result.rejected_by = "backend"
        return result

    level2_decision = await _route_level2(normalized, settings, matched_term=matched_term, raw_text=raw_text)
    if level2_decision:
        result.rejected = True
        result.rejected_by = level2_decision['rejected_by']
        result.reason_code = level2_decision['reason_code']
        result.code = level2_decision['code']
        result.ai_route = level2_decision.get('ai_route')
        result.ai_model = level2_decision.get('ai_model')
        result.ai_latency_ms = level2_decision.get('ai_latency_ms')
        result.matched_term = level2_decision.get('matched_term', matched_term)
        return result

    if matched_term and settings.moderation_ai_enabled:
        # Context AI evaluated as EDUCATIONAL or CLEAN, allow message
        result.rejected = False
        result.rejected_by = "moderation_ai_approved"
        result.matched_term = matched_term
        return result

    if matched_term:
        result.rejected = True
        result.code = "restricted_word"
        result.reason_code = "restricted_word"
        result.rejected_by = "level_1"
        result.matched_term = matched_term
        return result

    result.rejected = False
    result.rejected_by = "backend"
    return result


async def _route_level2(normalized: str, settings, matched_term: str = None, raw_text: str = None) -> Optional[dict]:
    """Level 2: Moderation routing. Invoke AI for context evaluation and language detection.

    Routes to:
    - Context AI (if dictionary match found):
        * Evaluates EDUCATIONAL, CLEAN, HARASSMENT, ABUSE
        * HARASSMENT/ABUSE → REJECT
        * EDUCATIONAL/CLEAN → ALLOW

    - Language AI (for non-English content):
        * Detects non-English abuse terms
        * LANGUAGE result → Policy depends on deployment
    """
    if settings.moderation_ai_enabled and matched_term:
        verdict = await check_context(normalized, matched_term=matched_term)
        logger.debug(f"Context verdict for '{matched_term}': {verdict.result}")

        if verdict.result in ("HARASSMENT", "ABUSE"):
            return {
                'rejected_by': 'moderation_ai',
                'reason_code': 'guidelines_violation',
                'code': 'guidelines_violation',
                'ai_route': 'context',
                'ai_model': 'claude-haiku-4-5',
                'matched_term': matched_term,
            }
        # EDUCATIONAL and CLEAN context → Allow (will be handled by caller)

    if settings.language_ai_enabled and not matched_term:
        # Only check language if no dictionary match (performance optimization)
        verdict = await check_language(normalized)
        if verdict.result == "LANGUAGE":
            logger.debug(f"Non-English content detected")
            return {
                'rejected_by': 'language_ai',
                'reason_code': 'language_violation',
                'code': 'language_violation',
                'ai_route': 'language',
                'ai_model': 'claude-haiku-4-5',
            }

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
    Only detects high-confidence spam to avoid false positives.

    Keyboard smash detection removed due to high false positive rate on legitimate text.
    Keyboard smash will be caught by Level 2 AI moderation if needed.
    """
    if not raw_text or len(raw_text) < 3:
        return False

    letters = sum(1 for c in raw_text if c.isalpha())
    total = len(raw_text)

    if total > 0 and (letters / total) < 0.2:
        return True

    return False


def _check_dictionary(normalized: str, single_words: Set[str], phrase_regex: Optional[re.Pattern]) -> Optional[str]:
    """Check against restricted words and phrases."""
    tokens = normalized.split()
    logger.debug(f"DEBUG _check_dictionary: tokens={tokens}, dict_size={len(single_words)}")

    for token in tokens:
        clean_token = re.sub(r'[^a-z0-9]', '', token)
        in_dict = clean_token in single_words if single_words else False
        logger.debug(f"DEBUG _check_dictionary: token='{token}' -> clean='{clean_token}' -> in_dict={in_dict}")
        if clean_token and in_dict:
            logger.info(f"DEBUG _check_dictionary: MATCH FOUND: '{clean_token}'")
            return clean_token

    if phrase_regex:
        match = phrase_regex.search(normalized)
        if match:
            logger.info(f"DEBUG _check_dictionary: PHRASE MATCH: '{match.group(1)}'")
            return match.group(1)

    logger.debug(f"DEBUG _check_dictionary: NO MATCH FOUND")
    return None


def _check_charset(normalized: str) -> bool:
    """Check for keyboard-smash (low alpha-char ratio)."""
    if not normalized:
        return False

    non_space = sum(1 for c in normalized if c != ' ')
    alpha = sum(1 for c in normalized if c.isalpha())

    if non_space > 0:
        ratio = alpha / non_space
        return ratio < 0.3

    return False
