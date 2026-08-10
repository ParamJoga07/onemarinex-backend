from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, func

from app.db.base import Base


class AgentRosterEvent(Base):
    """Durable audit record for agent-side vessel and crew unlink actions."""

    __tablename__ = "agent_roster_events"

    id = Column(Integer, primary_key=True, index=True)
    actor_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    vessel_id = Column(
        Integer, ForeignKey("vessels.id", ondelete="SET NULL"), nullable=True, index=True
    )
    crew_manifest_id = Column(Integer, nullable=True)
    action = Column(String(32), nullable=False, index=True)
    subject_name = Column(String(255), nullable=True)
    subject_hpid = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
