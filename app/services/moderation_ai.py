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
    result: Literal["EDUCATIONAL", "HARASSMENT", "ABUSE", "CLEAN"]
    confidence: float = 0.9
    reason: str = ""


_LANGUAGE_SYSTEM_PROMPT = """You are a language classifier for a community chat. Determine if text is primarily English or non-English.

RULES:
1. ENGLISH = Text in English language, including English with proper names
   - "Hello world" = ENGLISH
   - "Raj Kumar is amazing" = ENGLISH (English + Indian name)
   - "Joshan said goodbye" = ENGLISH (English + proper name)
   - "good morning everyone" = ENGLISH (English words only)

2. LANGUAGE = Text primarily in non-English language or untranslatable transliteration
   - "dengutha" = LANGUAGE (Telugu)
   - "hola amigo" = LANGUAGE (Spanish)
   - "你好" = LANGUAGE (Chinese)
   - "namaste" = LANGUAGE (Sanskrit)
   - Pure gibberish/keyboard smash = ENGLISH (default)

CRITICAL: Never reject English text with Indian names. When uncertain, default to ENGLISH.

Respond with ONE word:
ENGLISH
or
LANGUAGE

No explanation."""

_CONTEXT_SYSTEM_PROMPT = """You are a content moderator evaluating the CONTEXT and INTENT of text containing a flagged word.

The goal is to determine if the text is:
1. EDUCATIONAL - Academic/medical/informational use (e.g., "Porn addiction affects the brain")
2. CLEAN - Simple mention without intent to violate (e.g., "I like vanilla, not strawberry")
3. HARASSMENT - Personal attack or abuse directed at someone (e.g., "You are an idiot")
4. ABUSE - Explicit abuse, sexual solicitation, or hate speech (e.g., "Let's have sex", "I sell porn")

CLASSIFICATION RULES:
- EDUCATIONAL: Discussing a flagged term in informational/academic context
  * Example: "Porn addiction research shows brain changes"
  * Example: "Vaginal cancer symptoms include..."
  * Example: "Drug addiction treatment options"

- CLEAN: Legitimate mention without context suggesting violation
  * Example: "The word 'porn' has multiple meanings"
  * Example: "Criticism of policies is allowed"

- HARASSMENT: Direct personal attack or name-calling
  * Example: "You are an idiot"
  * Example: "All X people are criminals"
  * Indicator: Direct "you" or generalization about groups

- ABUSE: Explicit abuse, solicitation, or direct sexual/drug content
  * Example: "I sell porn"
  * Example: "Let's meet for sex"
  * Example: "Buy cocaine from me"
  * Indicator: Commercial transaction, direct proposition, or explicit language

Respond with ONLY the classification:
EDUCATIONAL
CLEAN
HARASSMENT
ABUSE

No explanation needed."""


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
        prompt = f"Evaluate this text containing '{matched_term}':\n\n{text}"

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
        verdict = _parse_verdict(text_content, "EDUCATIONAL", "CLEAN", "HARASSMENT", "ABUSE")
        logger.debug(f"Context check: {verdict} for '{matched_term}' (latency={latency_ms}ms)")

        return ContextVerdict(
            result=verdict,
            reason=f"ai_context_{matched_term.lower()}" if matched_term else "ai_context"
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
