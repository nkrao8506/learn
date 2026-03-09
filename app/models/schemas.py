"""
Pydantic schemas for API request/response validation.
"""
from datetime import datetime
from typing import Optional, List
from enum import Enum
from pydantic import BaseModel, Field, EmailStr, validator
import uuid


# Enums
class EventStatus(str, Enum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    AUTO_CREATED = "auto_created"


class FilterType(str, Enum):
    SENDER = "sender"
    LABEL = "label"
    DOMAIN = "domain"


class FilterAction(str, Enum):
    INCLUDE = "include"
    EXCLUDE = "exclude"


# Base schemas
class BaseResponse(BaseModel):
    """Base response schema with common fields."""
    class Config:
        from_attributes = True


# User schemas
class UserBase(BaseModel):
    email: EmailStr
    name: Optional[str] = None


class UserCreate(UserBase):
    google_id: str
    picture_url: Optional[str] = None


class UserResponse(UserBase):
    id: uuid.UUID
    picture_url: Optional[str] = None
    is_active: bool = True
    created_at: datetime

    class Config:
        from_attributes = True


# Auth schemas
class AuthCallback(BaseModel):
    code: str
    state: str


class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse


class TokenRefresh(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


# Event schemas
class EventBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = Field(None, max_length=5000)
    start_datetime: datetime
    end_datetime: Optional[datetime] = None
    timezone: str = Field(default="UTC", max_length=100)
    location: Optional[str] = Field(None, max_length=500)


class EventCreate(EventBase):
    source_email_id: str
    source_email_subject: Optional[str] = None
    source_email_sender: Optional[str] = None
    importance_score: float = Field(default=0.5, ge=0, le=1)
    confidence_score: float = Field(default=0.5, ge=0, le=1)


class EventUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=500)
    description: Optional[str] = Field(None, max_length=5000)
    start_datetime: Optional[datetime] = None
    end_datetime: Optional[datetime] = None
    timezone: Optional[str] = Field(None, max_length=100)
    location: Optional[str] = Field(None, max_length=500)

    @validator('end_datetime')
    def end_after_start(cls, v, values):
        if v and 'start_datetime' in values and values['start_datetime']:
            if v < values['start_datetime']:
                raise ValueError('end_datetime must be after start_datetime')
        return v


class EventResponse(EventBase):
    id: uuid.UUID
    user_id: uuid.UUID
    importance_score: float
    confidence_score: float
    status: EventStatus
    source_email_id: str
    source_email_subject: Optional[str]
    source_email_sender: Optional[str]
    calendar_event_id: Optional[str]
    calendar_synced_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class EventListResponse(BaseModel):
    events: List[EventResponse]
    total: int
    page: int
    page_size: int
    pages: int


class EventAcceptResponse(BaseModel):
    event: EventResponse
    calendar_event_id: str
    calendar_link: Optional[str] = None


# Settings schemas
class UserSettingsBase(BaseModel):
    auto_add_events: bool = False
    min_confidence_threshold: float = Field(default=0.7, ge=0, le=1)
    timezone: str = Field(default="UTC", max_length=100)
    email_notifications: bool = True


class UserSettingsUpdate(BaseModel):
    auto_add_events: Optional[bool] = None
    min_confidence_threshold: Optional[float] = Field(None, ge=0, le=1)
    timezone: Optional[str] = Field(None, max_length=100)
    email_notifications: Optional[bool] = None


class UserSettingsResponse(UserSettingsBase):
    id: uuid.UUID
    user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# Filter schemas
class FilterCreate(BaseModel):
    filter_type: FilterType
    filter_value: str = Field(..., min_length=1, max_length=255)
    action: FilterAction

    @validator('filter_value')
    def validate_filter_value(cls, v, values):
        if 'filter_type' in values:
            if values['filter_type'] == FilterType.DOMAIN:
                # Basic domain validation
                if '@' in v:
                    v = v.split('@')[-1]  # Extract domain from email
                if not v or '.' not in v:
                    raise ValueError('Invalid domain format')
        return v.lower()


class FilterResponse(FilterCreate):
    id: uuid.UUID
    user_id: uuid.UUID
    created_at: datetime

    class Config:
        from_attributes = True


class FilterListResponse(BaseModel):
    filters: List[FilterResponse]
    total: int


# Event extraction schemas
class EmailContent(BaseModel):
    """Input schema for event extraction."""
    message_id: str
    subject: Optional[str] = None
    sender: Optional[str] = None
    sender_email: Optional[str] = None
    body_text: Optional[str] = None
    body_html: Optional[str] = None
    date: Optional[datetime] = None
    labels: List[str] = []


class EventCandidate(BaseModel):
    """Output schema for event extraction."""
    title: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = Field(None, max_length=5000)
    start_datetime: datetime
    end_datetime: Optional[datetime] = None
    timezone: str = Field(default="UTC", max_length=100)
    location: Optional[str] = Field(None, max_length=500)
    importance_score: float = Field(default=0.5, ge=0, le=1)
    confidence_score: float = Field(default=0.5, ge=0, le=1)
    is_event: bool = True
    raw_extracted_data: Optional[dict] = None


class EventExtractionResult(BaseModel):
    """Result of event extraction process."""
    is_event: bool = False
    event: Optional[EventCandidate] = None
    extraction_method: str = "none"
    confidence: float = 0.0
    error: Optional[str] = None


# Pagination schemas
class PaginationParams(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class DateRangeFilter(BaseModel):
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None


# Webhook schemas
class GmailWebhookPayload(BaseModel):
    """Gmail Pub/Sub webhook payload."""
    message: dict
    subscription: str


class PubSubMessage(BaseModel):
    """Decoded Pub/Sub message."""
    data: str
    message_id: str
    publish_time: str


# Error schemas
class ErrorDetail(BaseModel):
    loc: List[str]
    msg: str
    type: str


class ErrorResponse(BaseModel):
    detail: str
    error_code: Optional[str] = None
    errors: Optional[List[ErrorDetail]] = None


# Health check
class HealthResponse(BaseModel):
    status: str
    version: str
    database: str
    environment: str
