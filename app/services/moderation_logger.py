"""Moderation event logging service.

Logs all moderation decisions with complete signal trails:
- Original and normalized messages
- All Level 1, Level 2, Level 3 signals
- Final decision with category, confidence, reason
- Timestamp and latency metrics
"""
import logging
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session

from app.db.models.chat_moderation_event import ChatModerationEvent
from app.services.moderation_policy import PolicyVerdict

logger = logging.getLogger("heyports.moderation_logger")


class ModerationLogger:
    """Log moderation events to database."""

    @staticmethod
    def log_event(
        db: Session,
        user_id: int,
        port_id: int,
        raw_message: str,
        normalized_message: str,
        policy_verdict: PolicyVerdict,
        matched_term: Optional[str] = None,
        rejected_by: Optional[str] = None,
        reason_code: Optional[str] = None,
        ai_route: Optional[str] = None,
        ai_model: Optional[str] = None,
        ai_latency_ms: Optional[int] = None,
        ai_context_verdict: Optional[str] = None,
        chat_message_id: Optional[int] = None,
    ) -> ChatModerationEvent:
        """Create and log a moderation event.

        Args:
            db: Database session
            user_id: User ID
            port_id: Port ID
            raw_message: Original message from user
            normalized_message: After text normalization
            policy_verdict: Final policy decision (ALLOW/FLAG/REJECT + category + reason)
            matched_term: Dictionary match (if any)
            rejected_by: Which layer rejected (level_1, level_2, moderation_ai, language_ai)
            reason_code: Technical reason code
            ai_route: AI route taken (language, context)
            ai_model: AI model used
            ai_latency_ms: AI call latency in milliseconds
            ai_context_verdict: AI context verdict (EDUCATIONAL, CLEAN, HARASSMENT, ABUSE)
            chat_message_id: Chat message ID (if message was stored)

        Returns:
            ChatModerationEvent record (saved to DB)
        """

        event = ChatModerationEvent(
            user_id=user_id,
            port_id=port_id,
            raw_message=raw_message,
            normalized_message=normalized_message,
            matched_term=matched_term,
            rejected_by=rejected_by,
            reason_code=reason_code,
            ai_route=ai_route,
            ai_model=ai_model,
            ai_latency_ms=ai_latency_ms,
            ai_context_verdict=ai_context_verdict,
            decision=policy_verdict.decision.value,
            category=policy_verdict.category.value,
            confidence=policy_verdict.confidence,
            reason=policy_verdict.reason or "No reason provided",
            moderation_layer=policy_verdict.level,
            chat_message_id=chat_message_id,
        )

        db.add(event)
        db.commit()
        db.refresh(event)

        logger.info(
            f"Moderation event logged: id={event.id} user={user_id} "
            f"decision={policy_verdict.decision} category={policy_verdict.category} "
            f"layer={policy_verdict.level} confidence={policy_verdict.confidence}"
        )

        return event

    @staticmethod
    def get_user_moderation_stats(db: Session, user_id: int, port_id: int = None) -> dict:
        """Get moderation statistics for a user."""
        query = db.query(ChatModerationEvent).filter(ChatModerationEvent.user_id == user_id)

        if port_id:
            query = query.filter(ChatModerationEvent.port_id == port_id)

        events = query.all()

        stats = {
            "total_events": len(events),
            "rejected": sum(1 for e in events if e.decision == "REJECT"),
            "flagged": sum(1 for e in events if e.decision == "FLAG"),
            "allowed": sum(1 for e in events if e.decision == "ALLOW"),
            "categories": {},
        }

        for event in events:
            if event.category:
                category = event.category
                stats["categories"][category] = stats["categories"].get(category, 0) + 1

        return stats
