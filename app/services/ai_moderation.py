import logging
import asyncio
from typing import Tuple
from app.core.config import settings
from app.utils.content_moderation import check_tier0_prechecks, check_tier1_local, is_benign_candidate

logger = logging.getLogger("heyports.ai_moderation")

SYSTEM_PROMPT = (
    "You are a strict community chat safety moderator. "
    "Classify if the message contains abusive language, severe profanity, hate speech, "
    "harassment, explicit sexual solicitation, or illegal content. "
    "Respond with ONLY one word: 'FLAGGED' or 'OK'."
)


async def check_tier3_anthropic(text: str) -> bool:
    """
    Tier 3: Anthropic Claude Haiku 4.5 AI Context Guardrail.
    Returns True if flagged as abusive, False if safe.
    """
    if not settings.ANTHROPIC_API_KEY:
        logger.debug("[AI Moderation] ANTHROPIC_API_KEY not set. Skipping AI check.")
        return False

    try:
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        model_name = getattr(settings, "ANTHROPIC_MODEL", "claude-haiku-4-5") or "claude-haiku-4-5"

        response = await asyncio.wait_for(
            client.messages.create(
                model=model_name,
                max_tokens=5,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": text}],
            ),
            timeout=2.5
        )

        result_text = ""
        for block in response.content:
            if getattr(block, "type", "") == "text":
                result_text += block.text

        is_flagged = "FLAGGED" in result_text.upper()
        logger.info(f"[AI Moderation] Claude evaluation for text: flagged={is_flagged}")
        return is_flagged

    except asyncio.TimeoutError:
        logger.warning("[AI Moderation] Anthropic API timed out (2.5s). Defaulting to safe.")
        return False
    except Exception as e:
        logger.error(f"[AI Moderation] Error calling Anthropic API: {e}")
        return False


async def moderate_message(text: str, user_id: int = 0) -> Tuple[bool, str]:
    """
    Multi-Tier Moderation Entry Point (Tier 0 -> Tier 1 -> Tier 2 -> Tier 3).
    Returns (is_blocked: bool, tier_used: str)
    """
    # Tier 0: Pre-checks (Rate limit, length, PII, URLs)
    is_tier0_blocked, reason = check_tier0_prechecks(text, user_id=user_id)
    if is_tier0_blocked:
        return True, f"tier0_{reason}"

    # Tier 1: Fast Local Profanity/Wordlist Check ($0 cost)
    if check_tier1_local(text):
        return True, "tier1"

    # Tier 2: Heuristic & Emoji Skip Gate ($0 cost)
    if is_benign_candidate(text):
        return False, "tier2"

    # Tier 3: Anthropic Claude Haiku 4.5 ($ minimal cost)
    is_abusive = await check_tier3_anthropic(text)
    return is_abusive, "tier3"
