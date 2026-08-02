"""Moderation policy engine.

Combines Level 1 (deterministic) and Level 2 (AI) signals into final decisions.
Implements ALLOW/FLAG/REJECT categories with configurable policies.

Three-tier decision structure:
- Level 1: Deterministic checks (fast, no AI)
- Level 2: AI context evaluation (for uncertain cases)
- Level 3: Policy engine (combines signals into final ALLOW/FLAG/REJECT)
"""
import logging
from enum import Enum
from typing import Optional, Dict, Any
from pydantic import BaseModel

logger = logging.getLogger("heyports.moderation_policy")


class Decision(str, Enum):
    """Final moderation decision."""
    ALLOW = "ALLOW"
    FLAG = "FLAG"
    REJECT = "REJECT"


class Category(str, Enum):
    """Content categories for logging and policy."""
    PROFANITY = "profanity"
    SEXUAL_CONTENT = "sexual_content"
    HARASSMENT = "harassment"
    HATE_SPEECH = "hate_speech"
    THREATS = "threats"
    SELF_HARM = "self_harm"
    CONTACT_INFO = "contact_info"
    PAYMENT_INFO = "payment_info"
    SPAM = "spam"
    EXTERNAL_LINK = "external_link"
    DUPLICATE = "duplicate"
    FLOOD = "flood"
    LANGUAGE_VIOLATION = "language_violation"
    CLEAN = "clean"


class PolicyVerdict(BaseModel):
    """Combined policy decision."""
    decision: Decision
    category: Category
    confidence: float = 0.95
    reason: str = ""
    level: str = "unknown"  # level_1, level_2, level_3


class ModerationPolicy:
    """Policy engine combining Level 1, Level 2, Level 3 signals."""

    # Default policy: balanced (not too strict, not too lenient)
    POLICY_STRICT = {
        "profanity": "REJECT",
        "sexual_content": "FLAG",
        "harassment": "REJECT",
        "hate_speech": "REJECT",
        "threats": "REJECT",
        "self_harm": "REJECT",
    }

    POLICY_LENIENT = {
        "profanity": "FLAG",
        "sexual_content": "FLAG",
        "harassment": "FLAG",
        "hate_speech": "REJECT",
        "threats": "REJECT",
        "self_harm": "REJECT",
    }

    POLICY_STANDARD = {
        "profanity": "REJECT",
        "sexual_content": "FLAG",
        "harassment": "REJECT",
        "hate_speech": "REJECT",
        "threats": "REJECT",
        "self_harm": "REJECT",
    }

    def __init__(self, policy_name: str = "standard"):
        """Initialize policy engine with named policy."""
        if policy_name == "strict":
            self.policy = self.POLICY_STRICT
        elif policy_name == "lenient":
            self.policy = self.POLICY_LENIENT
        else:
            self.policy = self.POLICY_STANDARD

        logger.info(f"Moderation policy initialized: {policy_name}")

    def decide(
        self,
        level1_code: Optional[str] = None,
        level2_verdict: Optional[str] = None,
        matched_term: Optional[str] = None,
        language: Optional[str] = None,
    ) -> PolicyVerdict:
        """Combine Level 1, Level 2, Level 3 signals into final decision.

        Args:
            level1_code: Level 1 rejection reason (e.g., 'spam', 'contact_info', 'restricted_word')
            level2_verdict: Level 2 AI verdict (e.g., 'EDUCATIONAL', 'ABUSE', 'HARASSMENT', 'LANGUAGE')
            matched_term: Matched restricted word from dictionary
            language: Language verdict (ENGLISH, LANGUAGE)

        Returns:
            PolicyVerdict with decision, category, confidence, reason, and level
        """

        # Level 1: Deterministic checks (reject if triggered)
        if level1_code:
            return self._decide_level1(level1_code, matched_term)

        # Level 2: AI context evaluation (for dictionary matches)
        if level2_verdict:
            return self._decide_level2(level2_verdict, matched_term, language)

        # Level 3: Default allow if no signals
        return PolicyVerdict(
            decision=Decision.ALLOW,
            category=Category.CLEAN,
            reason="No moderation issues detected",
            level="level_3",
            confidence=0.95,
        )

    def _decide_level1(
        self, level1_code: str, matched_term: Optional[str] = None
    ) -> PolicyVerdict:
        """Handle Level 1 deterministic decisions."""

        # Always reject these regardless of context
        if level1_code in ("flood", "duplicate", "rate_limited"):
            return PolicyVerdict(
                decision=Decision.REJECT,
                category=Category(level1_code),
                reason=f"User exceeded {level1_code} limits",
                level="level_1",
                confidence=1.0,
            )

        if level1_code == "empty":
            return PolicyVerdict(
                decision=Decision.REJECT,
                category=Category.SPAM,
                reason="Message is empty",
                level="level_1",
                confidence=1.0,
            )

        if level1_code == "too_long":
            return PolicyVerdict(
                decision=Decision.REJECT,
                category=Category.SPAM,
                reason="Message exceeds length limit",
                level="level_1",
                confidence=1.0,
            )

        if level1_code == "contact_info":
            return PolicyVerdict(
                decision=Decision.REJECT,
                category=Category.CONTACT_INFO,
                reason="Message contains contact information",
                level="level_1",
                confidence=1.0,
            )

        if level1_code == "payment_info":
            return PolicyVerdict(
                decision=Decision.REJECT,
                category=Category.PAYMENT_INFO,
                reason="Message contains payment information",
                level="level_1",
                confidence=1.0,
            )

        if level1_code == "external_link":
            return PolicyVerdict(
                decision=Decision.REJECT,
                category=Category.EXTERNAL_LINK,
                reason="Message contains external links",
                level="level_1",
                confidence=1.0,
            )

        if level1_code in ("spam", "charset"):
            return PolicyVerdict(
                decision=Decision.REJECT,
                category=Category.SPAM,
                reason="Message detected as spam or gibberish",
                level="level_1",
                confidence=1.0,
            )

        # restricted_word requires Level 2 context evaluation
        if level1_code == "restricted_word" and matched_term:
            # This shouldn't happen in normal flow (should go to Level 2)
            # But as fallback, reject with reason
            return PolicyVerdict(
                decision=Decision.REJECT,
                category=Category.PROFANITY,
                reason=f"Message contains restricted word: {matched_term}",
                level="level_1",
                confidence=0.85,
            )

        # Unknown level 1 code
        return PolicyVerdict(
            decision=Decision.REJECT,
            category=Category.SPAM,
            reason=f"Message failed moderation check: {level1_code}",
            level="level_1",
            confidence=0.9,
        )

    def _decide_level2(
        self,
        level2_verdict: str,
        matched_term: Optional[str] = None,
        language: Optional[str] = None,
    ) -> PolicyVerdict:
        """Handle Level 2 AI context decisions."""

        if level2_verdict == "EDUCATIONAL":
            return PolicyVerdict(
                decision=Decision.ALLOW,
                category=Category.CLEAN,
                reason=f"Educational context detected for term: {matched_term}",
                level="level_2",
                confidence=0.9,
            )

        if level2_verdict == "CLEAN":
            return PolicyVerdict(
                decision=Decision.ALLOW,
                category=Category.CLEAN,
                reason=f"Clean mention of term: {matched_term}",
                level="level_2",
                confidence=0.9,
            )

        if level2_verdict == "HARASSMENT":
            return PolicyVerdict(
                decision=Decision.REJECT,
                category=Category.HARASSMENT,
                reason=f"Personal attack or harassment detected with term: {matched_term}",
                level="level_2",
                confidence=0.85,
            )

        if level2_verdict == "ABUSE":
            return PolicyVerdict(
                decision=Decision.REJECT,
                category=Category.PROFANITY,
                reason=f"Explicit abuse detected with term: {matched_term}",
                level="level_2",
                confidence=0.85,
            )

        if level2_verdict == "LANGUAGE":
            # Non-English content detected
            # Policy: reject for now (can be made configurable)
            return PolicyVerdict(
                decision=Decision.REJECT,
                category=Category.LANGUAGE_VIOLATION,
                reason="Non-English content detected (policy: English only)",
                level="level_2",
                confidence=0.8,
            )

        # Fallback for unknown verdicts
        return PolicyVerdict(
            decision=Decision.REJECT,
            category=Category.SPAM,
            reason=f"Unknown AI verdict: {level2_verdict}",
            level="level_2",
            confidence=0.7,
        )

    def categorize(self, code: str) -> Category:
        """Map rejection code to category."""
        mapping = {
            "profanity": Category.PROFANITY,
            "sexual": Category.SEXUAL_CONTENT,
            "harassment": Category.HARASSMENT,
            "hate_speech": Category.HATE_SPEECH,
            "threat": Category.THREATS,
            "self_harm": Category.SELF_HARM,
            "contact_info": Category.CONTACT_INFO,
            "payment_info": Category.PAYMENT_INFO,
            "spam": Category.SPAM,
            "external_link": Category.EXTERNAL_LINK,
            "duplicate": Category.DUPLICATE,
            "flood": Category.FLOOD,
            "language": Category.LANGUAGE_VIOLATION,
        }
        return mapping.get(code, Category.CLEAN)
