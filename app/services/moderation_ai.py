"""Chat moderation via Anthropic Claude.

Provides two functions for content classification:
- check_language: Returns ENGLISH or LANGUAGE
- check_context: Returns context verdict (EDUCATIONAL, HARASSMENT, ABUSE, CLEAN)

Follows the project's "works without credentials" pattern: when ANTHROPIC_API_KEY
is unset (or a call fails) it returns a failure verdict and logs. The fail_closed
policy is recommended because failing open on moderation publishes abuse to a
public board.

Config:
    ANTHROPIC_API_KEY        enables real moderation; unset -> skipped
    CHAT_MODERATION_MODEL    override model (default claude-haiku-4-5)
    CHAT_MODERATION_TIMEOUT  call timeout in seconds (default 8.0)
    CHAT_MODERATION_FAIL_CLOSED  policy on call failure (default true)
    CHAT_MODERATION_MAX_RETRIES  max retries on transient failures (default 2)
"""
import logging
import os
import time
import re
import asyncio
from typing import Literal, Optional
from pydantic import BaseModel

logger = logging.getLogger("heyports.moderation_ai")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
MODEL = os.getenv("CHAT_MODERATION_MODEL", "claude-haiku-4-5")
TIMEOUT = float(os.getenv("CHAT_MODERATION_TIMEOUT", "8.0"))
FAIL_CLOSED = os.getenv("CHAT_MODERATION_FAIL_CLOSED", "true").lower() in ("1", "true", "yes", "on")
MAX_RETRIES = int(os.getenv("CHAT_MODERATION_MAX_RETRIES", "2"))

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
    confidence: float = 0.95


class ContextVerdict(BaseModel):
    result: Literal["CLEAN", "HARASSMENT", "ABUSE"]
    confidence: float = 0.9
    reason: str = ""


_LANGUAGE_SYSTEM_PROMPT = """You are the language classifier for HeyPorts Crew Chat.

Return exactly one word:

ENGLISH
- Message is primarily English.
- English containing names, places, ports or company names.
- Gibberish or unreadable text.

LANGUAGE
- Message is primarily a non-English language.
- Transliterated non-English (Telugu, Hindi, Tamil, etc.).

If uncertain, return ENGLISH.

Respond with only:

ENGLISH
LANGUAGE"""

_CONTEXT_SYSTEM_PROMPT = """You are the moderator for HeyPorts Crew Chat.

Classify the message into exactly one category.

CLEAN
- Normal conversation.
- Greetings.
- Operational discussion.
- Genuine complaints.
- Constructive criticism.
- Negative reviews or dissatisfaction without abuse.

HARASSMENT
- Personal abuse or bullying.
- Threats or violence.
- Hate speech.
- Discrimination against any person or group.
- Encouraging suicide or self-harm.

ABUSE
- Defamation or malicious attacks against HeyPorts.
- Calls to boycott, sabotage or damage HeyPorts.
- False accusations intended to harm HeyPorts' reputation.
- Illegal activity.
- Bribery or corruption.
- Drug solicitation.
- Prostitution solicitation.
- Grooming or coercion.

Do not reject genuine operational complaints or constructive feedback.

If uncertain, return CLEAN.

Respond with only one word:

CLEAN
HARASSMENT
ABUSE"""


async def check_language(text: str, attempt: int = 1) -> LanguageVerdict:
    """Classify text as English or other language. Never raises."""
    if not moderation_enabled():
        logger.warning("ANTHROPIC_API_KEY unset — returning default language verdict.")
        return LanguageVerdict(result="LANGUAGE")

    client = _get_client()
    if not client:
        return LanguageVerdict(result="LANGUAGE")

    try:
        start = time.time()
        resp = await client.messages.create(
            model=MODEL,
            max_tokens=32,
            system=_LANGUAGE_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": text[:2000],
            }],
        )
        latency_ms = int((time.time() - start) * 1000)

        text_content = next((b.text for b in resp.content if hasattr(b, 'text')), "")
        verdict = _parse_verdict(text_content, "ENGLISH", "LANGUAGE")
        logger.debug(f"Language check: {verdict} (latency={latency_ms}ms)")

        return LanguageVerdict(result=verdict)

    except asyncio.TimeoutError as e:
        logger.warning(f"Language check timeout (attempt {attempt}/{MAX_RETRIES})")
        if attempt < MAX_RETRIES:
            await asyncio.sleep(0.5 * attempt)  # Exponential backoff
            return await check_language(text, attempt + 1)
        if FAIL_CLOSED:
            return LanguageVerdict(result="LANGUAGE")
        return LanguageVerdict(result="ENGLISH")

    except Exception as e:
        logger.exception(f"Language check failed (attempt {attempt}/{MAX_RETRIES}): {str(e)}")
        if attempt < MAX_RETRIES:
            await asyncio.sleep(0.5 * attempt)
            return await check_language(text, attempt + 1)
        if FAIL_CLOSED:
            return LanguageVerdict(result="LANGUAGE")
        return LanguageVerdict(result="ENGLISH")


async def check_context(text: str, matched_term: str = "", attempt: int = 1) -> ContextVerdict:
    """Evaluate context of flagged content. Returns verdict and reason. Never raises."""
    if not moderation_enabled():
        logger.warning("ANTHROPIC_API_KEY unset — returning default context verdict.")
        return ContextVerdict(result="ABUSE", reason="moderation_disabled")

    client = _get_client()
    if not client:
        return ContextVerdict(result="ABUSE", reason="no_client")

    try:
        start = time.time()

        if matched_term:
            prompt = f"Evaluate this text containing '{matched_term}':\n\n{text}"
        else:
            prompt = f"Evaluate this text for contextual violations (threats, harassment, discrimination, illegal activity):\n\n{text}"

        resp = await client.messages.create(
            model=MODEL,
            max_tokens=32,
            system=_CONTEXT_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": prompt[:2000],
            }],
        )
        latency_ms = int((time.time() - start) * 1000)

        text_content = next((b.text for b in resp.content if hasattr(b, 'text')), "").strip()
        verdict = _parse_verdict(text_content, "CLEAN", "HARASSMENT", "ABUSE")

        reason = f"ai_context_{matched_term.lower()}" if matched_term else "ai_context_violation"
        logger.debug(f"Context check: {verdict} {reason} (latency={latency_ms}ms)")

        return ContextVerdict(
            result=verdict,
            reason=reason
        )

    except asyncio.TimeoutError as e:
        logger.warning(f"Context check timeout (attempt {attempt}/{MAX_RETRIES})")
        if attempt < MAX_RETRIES:
            await asyncio.sleep(0.5 * attempt)
            return await check_context(text, matched_term, attempt + 1)
        if FAIL_CLOSED:
            return ContextVerdict(result="ABUSE", reason="context_check_timeout")
        return ContextVerdict(result="CLEAN", reason="context_check_timeout")

    except Exception as e:
        logger.exception(f"Context check failed (attempt {attempt}/{MAX_RETRIES}): {str(e)}")
        if attempt < MAX_RETRIES:
            await asyncio.sleep(0.5 * attempt)
            return await check_context(text, matched_term, attempt + 1)
        if FAIL_CLOSED:
            return ContextVerdict(result="ABUSE", reason="context_check_error")
        return ContextVerdict(result="CLEAN", reason="context_check_error")


def _parse_verdict(text: str, *valid_options: str) -> str:
    """Extract and normalize verdict from response. Unrecognized defaults to first option."""
    if not text:
        return valid_options[0] if valid_options else ""

    cleaned = re.sub(r'[^A-Z_]', '', text.upper().strip())

    # Try exact match first
    for option in valid_options:
        if cleaned == option:
            return option

    # Try prefix match
    for option in valid_options:
        if cleaned.startswith(option):
            return option

    return valid_options[0] if valid_options else ""
