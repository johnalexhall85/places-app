from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    BigInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import relationship

from app.db import Base


class DemoAccessCode(Base):
    __tablename__ = "demo_access_codes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code_hash = Column(Text, nullable=False)
    code_label = Column(Text, nullable=False)
    recipient_name = Column(Text, nullable=True)
    recipient_email = Column(Text, nullable=True)
    organization = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    created_by = Column(Text, nullable=False, server_default=text("'system'"))
    is_active = Column(Boolean, nullable=False, server_default=text("true"))
    max_uses = Column(Integer, nullable=True)
    current_use_count = Column(Integer, nullable=False, server_default=text("0"))
    expires_at = Column(DateTime(timezone=True), nullable=True)
    last_used_at = Column(DateTime(timezone=True), nullable=True)

    events = relationship("DemoAccessEvent", back_populates="access_code")

    __table_args__ = (
        UniqueConstraint("code_hash", name="uq_demo_access_codes_code_hash"),
        CheckConstraint("current_use_count >= 0", name="ck_demo_access_codes_use_count_nonnegative"),
        CheckConstraint("max_uses IS NULL OR max_uses > 0", name="ck_demo_access_codes_max_uses_positive"),
        Index("idx_demo_access_codes_active", "is_active"),
        Index("idx_demo_access_codes_recipient_email", "recipient_email"),
        Index("idx_demo_access_codes_last_used_at", "last_used_at"),
    )


class DemoAccessEvent(Base):
    __tablename__ = "demo_access_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    access_code_id = Column(
        Integer,
        ForeignKey("demo_access_codes.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_type = Column(Text, nullable=False)
    occurred_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    ip_address = Column(Text, nullable=True)
    user_agent = Column(Text, nullable=True)
    session_id = Column(Text, nullable=True)
    request_path = Column(Text, nullable=True)
    referrer = Column(Text, nullable=True)
    success = Column(Boolean, nullable=False, server_default=text("false"))
    failure_reason = Column(Text, nullable=True)

    access_code = relationship("DemoAccessCode", back_populates="events")

    __table_args__ = (
        Index("idx_demo_access_events_code_time", "access_code_id", "occurred_at"),
        Index("idx_demo_access_events_type_time", "event_type", "occurred_at"),
        Index("idx_demo_access_events_session", "session_id"),
    )

