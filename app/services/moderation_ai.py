"""Chat moderation via Anthropic Claude.

Provides two functions for content classification:
- check_language: Returns ENGLISH or LANGUAGE
- check_moderation: Returns OK or FLAGGED

Follows the project's "works without credentials" pattern: when ANTHROPIC_API_KEY
is unset (or a call fails) it returns a failure verdict and logs. The fail_closed
policy is recommended because failing open on moderation publishes abuse to a
public board.

Config:
    ANTHROPIC_API_KEY        enables real moderation; unset -> skipped
    CHAT_MODERATION_MODEL    override model (default claude-opus-5)
    CHAT_MODERATION_TIMEOUT  call timeout in seconds (default 8.0)
    CHAT_MODERATION_FAIL_CLOSED  policy on call failure (default true)
"""
import logging
import os
import time
import re
from typing import Literal, Optional
from pydantic import BaseModel

logger = logging.getLogger("heyports.moderation_ai")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
MODEL = os.getenv("CHAT_MODERATION_MODEL", "claude-haiku-4-5")
TIMEOUT = float(os.getenv("CHAT_MODERATION_TIMEOUT", "8.0"))
FAIL_CLOSED = os.getenv("CHAT_MODERATION_FAIL_CLOSED", "true").lower() in ("1", "true", "yes", "on")

_client = None


def _get_client():
    global _client
    if _client is None and ANTHROPIC_API_KEY:
        import anthropic
        _client = anthropic.AsyncAnthropic(
            api_key=ANTHROPIC_API_KEY,
            timeout=TIMEOUT,
            max_retries=1,
        )
    return _client


def moderation_enabled() -> bool:
    return bool(ANTHROPIC_API_KEY)


class LanguageVerdict(BaseModel):
    result: Literal["ENGLISH", "LANGUAGE"]


class ModerationVerdict(BaseModel):
    result: Literal["OK", "FLAGGED"]


_LANGUAGE_SYSTEM_PROMPT = """Classify if text is English or non-English.

CRITICAL RULES:
1. If text contains mostly English words + proper names = ENGLISH (Examples: "raj kumar is idiot", "Joshan said hello")
2. Common English words (hello, is, are, the, and, or) = ENGLISH
3. Gibberish (asdfgh, qwerty) = ENGLISH (default when unsure)
4. Pure foreign words/transliterations = LANGUAGE (Examples: dengutha, bagunnara, hola, namaste)
5. Non-Latin scripts = LANGUAGE (Chinese, Arabic, Russian, Hindi scripts)

CRITICAL DISTINCTION:
- "raj kumar is idiot" = ENGLISH (English sentence with Indian name)
- "dengutha bagunnara" = LANGUAGE (pure Telugu transliterations)
- "Joshan is idiot" = ENGLISH (English sentence with proper name)
- "hola amigo" = LANGUAGE (Spanish words)

Examples:
- hello = ENGLISH
- Hello World = ENGLISH
- raj kumar is idiot = ENGLISH (proper name + English words)
- Joshan said hello = ENGLISH (proper name + English)
- are any prostitutes = ENGLISH (English words only)
- dengutha = LANGUAGE (Telugu transliteration, not English word)
- bagunnara = LANGUAGE (Telugu transliteration)
- hola = LANGUAGE (Spanish word)
- 你好 = LANGUAGE (Chinese)

Respond with ONE word only:
- ENGLISH
- LANGUAGE

No explanations."""

_LANGUAGE_USER_PROMPT = "{text}"

_MODERATION_SYSTEM_PROMPT = """You are a strict content moderation classifier for a crew community chat. Determine if text violates community guidelines.

STRICT PROHIBITION - Flag immediately if text contains:
1. PROFANITY: Any swear words, curse words, or crude language (fuck, shit, damn, etc.) - be VERY strict
2. VERBAL ABUSE: Insults, name-calling, personal attacks (idiot, retard, loser, etc.)
3. HARASSMENT: Threats, intimidation, or hostile language toward any person/group
4. SEXUAL CONTENT: Sexual references, explicit material, innuendo
5. DISCRIMINATION: Slurs, racism, sexism, or hate speech toward any identity group
6. CONTEXTUAL RED FLAGS: Solicitation, illegal activity proposals, escort services, drug dealing
7. SPAM: Commercial spam, repeated advertisements, scams

Be AGGRESSIVE - default to FLAG any questionable content. Crew safety is paramount.

Respond with a single word only:
- "OK" if text is completely clean
- "FLAGGED" if text violates ANY guideline above

Do not include XML tags or explanations."""

_MODERATION_USER_PROMPT = "STRICT MODERATION CHECK - Flag if inappropriate:\n{text}"


async def check_language(text: str) -> LanguageVerdict:
    """Classify text as English or other language. Never raises."""
    if not moderation_enabled():
        logger.warning("ANTHROPIC_API_KEY unset — returning default language verdict.")
        return LanguageVerdict(result="LANGUAGE")

    client = _get_client()
    if not client:
        return LanguageVerdict(result="LANGUAGE")

    try:
        start = time.time()
        kwargs = {
            "model": MODEL,
            "max_tokens": 256,
            "system": _LANGUAGE_SYSTEM_PROMPT,
            "messages": [{
                "role": "user",
                "content": _LANGUAGE_USER_PROMPT.format(text=text[:2000]),
            }],
        }
        if "opus-5" in MODEL.lower():
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": 512}
        resp = await client.messages.create(**kwargs)
        latency_ms = int((time.time() - start) * 1000)

        text_content = next((b.text for b in resp.content if hasattr(b, 'text')), "")
        verdict = _parse_verdict(text_content, "ENGLISH", "LANGUAGE")

        return LanguageVerdict(result=verdict)

    except Exception as e:
        logger.exception("Language check failed: %s", str(e))
        if FAIL_CLOSED:
            return LanguageVerdict(result="LANGUAGE")  # Reject on error
        return LanguageVerdict(result="ENGLISH")  # Allow if not fail-closed


async def check_moderation(text: str) -> ModerationVerdict:
    """Classify text for guideline violations. Never raises."""
    if not moderation_enabled():
        logger.warning("ANTHROPIC_API_KEY unset — returning default moderation verdict.")
        return ModerationVerdict(result="OK")

    client = _get_client()
    if not client:
        return ModerationVerdict(result="OK")

    try:
        start = time.time()
        kwargs = {
            "model": MODEL,
            "max_tokens": 256,
            "system": _MODERATION_SYSTEM_PROMPT,
            "messages": [{
                "role": "user",
                "content": _MODERATION_USER_PROMPT.format(text=text[:2000]),
            }],
        }
        if "opus-5" in MODEL.lower():
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": 512}
        resp = await client.messages.create(**kwargs)
        latency_ms = int((time.time() - start) * 1000)

        text_content = next((b.text for b in resp.content if hasattr(b, 'text')), "")
        verdict = _parse_verdict(text_content, "OK", "FLAGGED")

        return ModerationVerdict(result=verdict)

    except Exception as e:
        logger.exception("Moderation check failed: %s", str(e))
        if FAIL_CLOSED:
            return ModerationVerdict(result="FLAGGED")  # Reject on error (safer)
        return ModerationVerdict(result="OK")  # Allow if not fail-closed


def _parse_verdict(text: str, *valid_options: str) -> str:
    """Extract and normalize verdict from response. Unrecognized defaults to first option."""
    if not text:
        return valid_options[0] if valid_options else ""

    cleaned = re.sub(r'[^A-Z_]', '', text.upper().strip())
    for option in valid_options:
        if cleaned == option or cleaned.startswith(option):
            return option

    return valid_options[0] if valid_options else ""
