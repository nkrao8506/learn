"""
SQLAlchemy ORM models for the application.
"""
import uuid
from datetime import datetime
from typing import Optional, List
from enum import Enum
from sqlalchemy import (
    Column, String, Text, Boolean, Float, DateTime, ForeignKey,
    Integer, BigInteger, Enum as SQLEnum, Index, JSON
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class EventStatus(str, Enum):
    """Status of an event in the system."""
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    AUTO_CREATED = "auto_created"


class ProcessingResult(str, Enum):
    """Result of processing a Gmail message."""
    EVENT_CREATED = "event_created"
    NO_EVENT = "no_event"
    FILTERED_OUT = "filtered_out"
    ERROR = "error"


class FilterAction(str, Enum):
    """Action to take for a filter."""
    INCLUDE = "include"
    EXCLUDE = "exclude"


class FilterType(str, Enum):
    """Type of filter."""
    SENDER = "sender"
    LABEL = "label"
    DOMAIN = "domain"


class User(Base):
    """User model representing a registered user."""
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    google_id = Column(String(255), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=True)
    picture_url = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    oauth_token = relationship("OAuthToken", back_populates="user", uselist=False, lazy="selectin")
    settings = relationship("UserSettings", back_populates="user", uselist=False, lazy="selectin")
    filters = relationship("Filter", back_populates="user", lazy="selectin")
    events = relationship("Event", back_populates="user", lazy="dynamic")
    processed_messages = relationship("ProcessedMessage", back_populates="user", lazy="dynamic")
    gmail_watch = relationship("GmailWatch", back_populates="user", uselist=False, lazy="selectin")

    def __repr__(self):
        return f"<User(id={self.id}, email={self.email})>"


class OAuthToken(Base):
    """OAuth tokens for a user (encrypted storage)."""
    __tablename__ = "oauth_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    access_token = Column(Text, nullable=False)  # Encrypted
    refresh_token = Column(Text, nullable=False)  # Encrypted
    token_type = Column(String(50), default="Bearer", nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    scope = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    user = relationship("User", back_populates="oauth_token")

    def __repr__(self):
        return f"<OAuthToken(user_id={self.user_id})>"


class UserSettings(Base):
    """User-specific settings for event processing."""
    __tablename__ = "user_settings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    auto_add_events = Column(Boolean, default=False, nullable=False)
    min_confidence_threshold = Column(Float, default=0.7, nullable=False)
    timezone = Column(String(100), default="UTC", nullable=False)
    email_notifications = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    user = relationship("User", back_populates="settings")

    def __repr__(self):
        return f"<UserSettings(user_id={self.user_id}, auto_add={self.auto_add_events})>"


class Filter(Base):
    """User-defined filters for email processing."""
    __tablename__ = "filters"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    filter_type = Column(String(50), nullable=False)
    filter_value = Column(String(255), nullable=False)
    action = Column(String(50), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    user = relationship("User", back_populates="filters")

    __table_args__ = (
        Index("ix_filters_user_type_value", "user_id", "filter_type", "filter_value", unique=True),
    )

    def __repr__(self):
        return f"<Filter(user_id={self.user_id}, type={self.filter_type}, value={self.filter_value})>"


class ProcessedMessage(Base):
    """Record of processed Gmail messages to avoid duplicates."""
    __tablename__ = "processed_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    gmail_message_id = Column(String(255), nullable=False)
    gmail_thread_id = Column(String(255), nullable=True)
    processed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    result = Column(String(50), nullable=True)
    error_message = Column(Text, nullable=True)

    # Relationships
    user = relationship("User", back_populates="processed_messages")

    __table_args__ = (
        Index("ix_processed_messages_user_msg", "user_id", "gmail_message_id", unique=True),
        Index("ix_processed_messages_processed_at", "processed_at"),
    )

    def __repr__(self):
        return f"<ProcessedMessage(id={self.gmail_message_id}, result={self.result})>"


class Event(Base):
    """Event extracted from an email."""
    __tablename__ = "events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    start_datetime = Column(DateTime(timezone=True), nullable=False, index=True)
    end_datetime = Column(DateTime(timezone=True), nullable=True)
    timezone = Column(String(100), default="UTC", nullable=False)
    location = Column(String(500), nullable=True)
    importance_score = Column(Float, default=0.5, nullable=False)
    confidence_score = Column(Float, default=0.5, nullable=False)
    status = Column(String(50), default=EventStatus.PROPOSED.value, nullable=False)
    
    # Source email info
    source_email_id = Column(String(255), nullable=False)
    source_email_subject = Column(String(500), nullable=True)
    source_email_sender = Column(String(255), nullable=True)
    
    # Calendar integration
    calendar_event_id = Column(String(255), nullable=True)
    calendar_synced_at = Column(DateTime(timezone=True), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    user = relationship("User", back_populates="events")

    __table_args__ = (
        Index("ix_events_user_status", "user_id", "status"),
        Index("ix_events_start_date", "start_datetime"),
        Index("ix_events_source_email", "source_email_id"),
    )

    def __repr__(self):
        return f"<Event(id={self.id}, title={self.title}, status={self.status})>"


class GmailWatch(Base):
    """Gmail Pub/Sub watch subscription for a user."""
    __tablename__ = "gmail_watches"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    history_id = Column(BigInteger, nullable=False)
    expiration = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    user = relationship("User", back_populates="gmail_watch")

    def __repr__(self):
        return f"<GmailWatch(user_id={self.user_id}, history_id={self.history_id})>"


class AuditLog(Base):
    """Audit log for tracking important actions."""
    __tablename__ = "audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action = Column(String(100), nullable=False)
    resource_type = Column(String(50), nullable=True)
    resource_id = Column(UUID(as_uuid=True), nullable=True)
    details = Column(JSONB, nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_audit_logs_user_created", "user_id", "created_at"),
    )

    def __repr__(self):
        return f"<AuditLog(action={self.action}, user_id={self.user_id})>"
