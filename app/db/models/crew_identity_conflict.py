from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class CrewIdentityConflictRecord(Base):
    """A durable, human-resolved identity ambiguity.

    The queue records evidence; it never merges CrewProfile rows. A resolved
    selection only authorizes a later manifest retry to link one exact profile
    or deliberately leave the manifest pending.
    """

    __tablename__ = "crew_identity_conflicts"
    __table_args__ = (
        Index(
            "ix_crew_identity_conflicts_queue",
            "status",
            "created_at",
        ),
        Index(
            "ix_crew_identity_conflicts_identity",
            "vessel_id",
            "passport_key",
            "created_at",
        ),
        Index(
            "uq_crew_identity_conflicts_open_identity",
            "vessel_id",
            "passport_key",
            "identity_fingerprint",
            unique=True,
            postgresql_where=text("status = 'OPEN'"),
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    operation = Column(String(32), nullable=False)
    vessel_id = Column(
        Integer, ForeignKey("vessels.id", ondelete="SET NULL"), nullable=True, index=True
    )
    passport_key = Column(String(128), nullable=False, index=True)
    identity_fingerprint = Column(String(64), nullable=False, index=True)
    proposed_identity = Column(JSON, nullable=False)
    candidate_profile_ids = Column(JSON, nullable=False, default=list)
    conflict_message = Column(Text, nullable=False)
    status = Column(String(16), nullable=False, default="OPEN", server_default="OPEN")
    version = Column(Integer, nullable=False, default=1, server_default="1")

    resolution_action = Column(String(32), nullable=True)
    selected_profile_id = Column(
        Integer, ForeignKey("crew_profiles.id", ondelete="SET NULL"), nullable=True, index=True
    )
    evidence_type = Column(String(64), nullable=True)
    evidence_reference = Column(String(255), nullable=True)
    resolution_reason = Column(Text, nullable=True)
    resolved_by_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=func.now())

    vessel = relationship("Vessel")
    selected_profile = relationship("CrewProfile")
    resolved_by = relationship("User")


class CrewIdentityConflictAudit(Base):
    """Append-only before/after evidence for an identity queue decision."""

    __tablename__ = "crew_identity_conflict_audits"

    id = Column(Integer, primary_key=True, index=True)
    conflict_id = Column(
        Integer,
        ForeignKey("crew_identity_conflicts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    actor_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action = Column(String(32), nullable=False)
    expected_version = Column(Integer, nullable=False)
    before_state = Column(JSON, nullable=False)
    after_state = Column(JSON, nullable=False)
    evidence_type = Column(String(64), nullable=False)
    evidence_reference = Column(String(255), nullable=True)
    reason = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    conflict = relationship("CrewIdentityConflictRecord")
    actor = relationship("User")
