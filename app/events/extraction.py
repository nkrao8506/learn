"""
Event extraction service with heuristic filtering and LLM-based extraction.
"""
import re
import json
import html
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from abc import ABC, abstractmethod

from app.core.config import settings
from app.models.schemas import EmailContent, EventCandidate, EventExtractionResult
from app.events.llm_provider import call_llm_json, get_llm_provider


class EventExtractorInterface(ABC):
    """Abstract interface for event extractors."""

    @abstractmethod
    async def extract(self, email: EmailContent) -> EventExtractionResult:
        """Extract event information from an email."""
        pass


class HeuristicFilter:
    """
    Heuristic filter to quickly identify emails that might contain events.
    Uses keyword matching, sender analysis, and pattern recognition.
    """

    # Keywords that suggest an event
    EVENT_KEYWORDS = [
        "meeting", "appointment", "event", "call", "conference",
        "webinar", "workshop", "schedule", "reservation", "booking",
        "interview", "presentation", "demo", "training", "session",
        "invitation", "invite", "rsvp", "calendar", "reminder",
        "sync", "standup", "retro", "planning", "review",
        "deadline", "due", "starts", "begins", "join us",
    ]

    # Sender domains that typically send calendar invites
    CALENDAR_DOMAINS = [
        "calendar.google.com",
        "outlook.com",
        "calendar.live.com",
        "zoom.us",
        "teams.microsoft.com",
        "meet.google.com",
        "webex.com",
        "gotomeeting.com",
        "calendly.com",
        "acuityscheduling.com",
        "doodle.com",
        "eventbrite.com",
        "meetup.com",
    ]

    # Patterns that suggest date/time
    DATETIME_PATTERNS = [
        r'\d{1,2}[/-]\d{1,2}[/-]\d{2,4}',  # Date patterns
        r'(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*,?\s+\w+\s+\d{1,2}',
        r'\d{1,2}:\d{2}\s*(?:am|pm|AM|PM)',
        r'(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}',
        r'next\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)',
        r'tomorrow\s+at',
        r'on\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)',
    ]

    # Subject patterns that indicate non-events
    NON_EVENT_PATTERNS = [
        r'^re:',  # Reply
        r'^fw:',  # Forward
        r'^fwd:',  # Forward
        r'canceled',  # Cancellation
        r'cancelled',
        r'reminder: your subscription',  # Subscription reminders
        r'order confirmation',
        r'receipt',
        r'invoice',
        r'your purchase',
    ]

    def __init__(self, custom_keywords: List[str] = None):
        self.keywords = set(self.EVENT_KEYWORDS)
        if custom_keywords:
            self.keywords.update(custom_keywords)

    def check_sender(self, email: EmailContent) -> tuple[bool, float]:
        """
        Check if sender suggests an event.
        Returns (is_event_sender, confidence).
        """
        sender_email = email.sender_email or ""
        sender = email.sender or ""
        sender_lower = sender_email.lower()
        
        # Check for calendar domains
        for domain in self.CALENDAR_DOMAINS:
            if domain in sender_lower:
                return True, 0.9
        
        # Check for calendar-like sender names
        calendar_senders = ["calendar", "notifications", "noreply", "no-reply"]
        for cs in calendar_senders:
            if cs in sender_lower:
                return True, 0.7
        
        return False, 0.0

    def check_subject(self, email: EmailContent) -> tuple[bool, float]:
        """
        Check if subject suggests an event.
        Returns (is_event_subject, confidence).
        """
        subject = (email.subject or "").lower()
        
        # Check non-event patterns first
        for pattern in self.NON_EVENT_PATTERNS:
            if re.search(pattern, subject, re.IGNORECASE):
                return False, 0.0
        
        # Check for keywords
        keyword_matches = sum(1 for kw in self.keywords if kw in subject)
        if keyword_matches > 0:
            confidence = min(0.9, 0.5 + keyword_matches * 0.1)
            return True, confidence
        
        return False, 0.0

    def check_body(self, email: EmailContent) -> tuple[bool, float]:
        """
        Check if body contains event indicators.
        Returns (has_event_indicators, confidence).
        """
        body = (email.body_text or "").lower()
        if not body:
            return False, 0.0
        
        # Check for datetime patterns
        datetime_matches = 0
        for pattern in self.DATETIME_PATTERNS:
            if re.search(pattern, body, re.IGNORECASE):
                datetime_matches += 1
        
        # Check for keywords
        keyword_matches = sum(1 for kw in self.keywords if kw in body)
        
        # Check for action words with time context
        action_patterns = [
            r'join\s+(?:the\s+)?(?:meeting|call|webinar)',
            r'click\s+here\s+to\s+join',
            r'dial-in',
            r'meeting\s+(?:id|link|url)',
            r'video\s+call',
            r'google\s+meet',
            r'zoom\s+meeting',
            r'teams\s+meeting',
        ]
        action_matches = sum(1 for p in action_patterns if re.search(p, body))
        
        # Calculate confidence
        if datetime_matches > 0 and keyword_matches > 0:
            return True, min(0.9, 0.6 + datetime_matches * 0.1 + keyword_matches * 0.05)
        elif datetime_matches > 0:
            return True, min(0.7, 0.4 + datetime_matches * 0.1)
        elif keyword_matches > 1:
            return True, min(0.6, 0.4 + keyword_matches * 0.05)
        elif action_matches > 0:
            return True, 0.7
        
        return False, 0.0

    def should_process(self, email: EmailContent) -> tuple[bool, float]:
        """
        Determine if an email should be processed for event extraction.
        Returns (should_process, initial_confidence).
        """
        # Check sender
        sender_match, sender_conf = self.check_sender(email)
        if sender_match and sender_conf >= 0.9:
            return True, sender_conf
        
        # Check subject
        subject_match, subject_conf = self.check_subject(email)
        
        # Check body
        body_match, body_conf = self.check_body(email)
        
        # Combine results
        if sender_match or subject_match or body_match:
            confidence = max(sender_conf, subject_conf, body_conf)
            return True, confidence
        
        return False, 0.0


class LLMEventExtractor:
    """
    LLM-based event extractor.
    Uses the abstracted LLM interface to extract structured event data.
    """

    SYSTEM_PROMPT = """You are an expert at extracting event information from emails.
Your task is to analyze email content and determine if it contains an event/meeting/appointment.
If an event is found, extract all relevant details in JSON format.
Be precise with dates, times, and locations.
If the email does not contain an event, indicate that clearly."""

    EXTRACTION_PROMPT = """Analyze the following email and extract event information.

EMAIL DETAILS:
Subject: {subject}
Sender: {sender}
Date: {date}

EMAIL BODY:
{body}

INSTRUCTIONS:
1. Determine if this email contains information about an event, meeting, appointment, or scheduled activity.
2. If YES, extract the following information in JSON format:
   - title: A clear, concise title for the event (max 100 characters)
   - description: A brief description of the event (max 500 characters)
   - start_datetime: The start date and time in ISO 8601 format (YYYY-MM-DDTHH:MM:SS)
   - end_datetime: The end date and time in ISO 8601 format (if specified, otherwise null)
   - timezone: The timezone (default to "UTC" if not specified)
   - location: The location or meeting link (if specified)
   - importance_score: A score from 0-1 indicating how important this event likely is
   - confidence_score: A score from 0-1 indicating your confidence in the extraction

3. If NO event is found, return: {{"is_event": false, "reason": "explanation"}}

4. If the email is a reply/forward that doesn't contain new event information, return: {{"is_event": false, "reason": "not a new event"}}

RESPOND WITH VALID JSON ONLY. No other text.
"""

    def __init__(self, provider=None):
        self.provider = provider or get_llm_provider()

    def _sanitize_text(self, text: str) -> str:
        """Sanitize text to prevent injection and clean up."""
        if not text:
            return ""
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', ' ', text)
        # Decode HTML entities
        text = html.unescape(text)
        # Remove excessive whitespace
        text = re.sub(r'\s+', ' ', text)
        # Truncate
        return text.strip()[:5000]

    def _parse_datetime(self, dt_str: str) -> Optional[datetime]:
        """Parse datetime string to datetime object."""
        if not dt_str:
            return None
        
        # Common datetime formats
        formats = [
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d",
        ]
        
        for fmt in formats:
            try:
                return datetime.strptime(dt_str, fmt)
            except ValueError:
                continue
        
        return None

    def _validate_event_data(self, data: Dict[str, Any]) -> EventCandidate:
        """Validate and sanitize LLM output."""
        if not data.get("is_event", False):
            return None
        
        # Required fields
        title = data.get("title", "")
        if not title or len(title) < 2:
            return None
        
        # Parse and validate datetime
        start_str = data.get("start_datetime")
        if not start_str:
            return None
        
        start_dt = self._parse_datetime(start_str)
        if not start_dt:
            return None
        
        # Parse end datetime
        end_dt = None
        end_str = data.get("end_datetime")
        if end_str:
            end_dt = self._parse_datetime(end_str)
        
        # If no end time, default to 1 hour after start
        if not end_dt:
            end_dt = start_dt + timedelta(hours=1)
        
        # Validate end is after start
        if end_dt <= start_dt:
            end_dt = start_dt + timedelta(hours=1)
        
        # Sanitize text fields
        title = self._sanitize_text(title)[:500]
        description = self._sanitize_text(data.get("description", ""))[:5000]
        location = self._sanitize_text(data.get("location", ""))[:500]
        
        # Validate scores
        importance = float(data.get("importance_score", 0.5))
        importance = max(0.0, min(1.0, importance))
        
        confidence = float(data.get("confidence_score", 0.5))
        confidence = max(0.0, min(1.0, confidence))
        
        # Validate timezone
        timezone = data.get("timezone", "UTC")
        if not timezone or len(timezone) > 100:
            timezone = "UTC"
        
        return EventCandidate(
            title=title,
            description=description,
            start_datetime=start_dt,
            end_datetime=end_dt,
            timezone=timezone,
            location=location,
            importance_score=importance,
            confidence_score=confidence,
            is_event=True,
            raw_extracted_data=data,
        )

    async def extract(self, email: EmailContent) -> EventExtractionResult:
        """Extract event information from an email using LLM."""
        try:
            # Prepare prompt
            prompt = self.EXTRACTION_PROMPT.format(
                subject=self._sanitize_text(email.subject or "No subject"),
                sender=email.sender or email.sender_email or "Unknown",
                date=str(email.date) if email.date else "Unknown",
                body=self._sanitize_text(email.body_text or email.body_html or "No content"),
            )
            
            # Call LLM
            result = await call_llm_json(
                prompt=prompt,
                system_prompt=self.SYSTEM_PROMPT,
                provider=self.provider,
            )
            
            # Check if event was found
            if not result.get("is_event", False):
                return EventExtractionResult(
                    is_event=False,
                    extraction_method="llm",
                    confidence=0.0,
                    error=result.get("reason", "No event detected"),
                )
            
            # Validate and create event candidate
            event = self._validate_event_data(result)
            if not event:
                return EventExtractionResult(
                    is_event=False,
                    extraction_method="llm",
                    confidence=0.0,
                    error="Failed to validate event data",
                )
            
            return EventExtractionResult(
                is_event=True,
                event=event,
                extraction_method="llm",
                confidence=event.confidence_score,
            )
            
        except Exception as e:
            return EventExtractionResult(
                is_event=False,
                extraction_method="llm",
                confidence=0.0,
                error=str(e),
            )


class EventExtractionService:
    """
    Main event extraction service that combines heuristic filtering
    with LLM-based extraction.
    """

    def __init__(self, provider=None):
        self.heuristic = HeuristicFilter()
        self.llm_extractor = LLMEventExtractor(provider)

    async def extract(self, email: EmailContent) -> EventExtractionResult:
        """
        Extract event information from an email.
        First applies heuristics, then uses LLM if needed.
        """
        # Step 1: Apply heuristic filter
        should_process, initial_confidence = self.heuristic.should_process(email)
        
        if not should_process:
            return EventExtractionResult(
                is_event=False,
                extraction_method="heuristic_reject",
                confidence=initial_confidence,
                error="Email rejected by heuristic filter",
            )
        
        # Step 2: Use LLM for detailed extraction
        result = await self.llm_extractor.extract(email)
        
        # Adjust confidence based on heuristic match
        if result.is_event and result.event:
            # Boost confidence if heuristics also matched strongly
            result.event.confidence_score = min(
                1.0,
                result.event.confidence_score * 0.8 + initial_confidence * 0.2
            )
            result.confidence = result.event.confidence_score
        
        return result

    async def batch_extract(
        self,
        emails: List[EmailContent]
    ) -> List[EventExtractionResult]:
        """Extract events from multiple emails."""
        results = []
        for email in emails:
            result = await self.extract(email)
            results.append(result)
        return results
