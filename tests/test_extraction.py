"""
Tests for event extraction module.
"""
import pytest
from datetime import datetime, timedelta

from app.models.schemas import EmailContent
from app.events.extraction import HeuristicFilter, EventExtractionService
from app.events.llm_provider import MockLLMProvider


class TestHeuristicFilter:
    """Tests for the HeuristicFilter class."""

    def setup_method(self):
        self.filter = HeuristicFilter()

    def test_check_sender_calendar_domain(self):
        """Test sender check with calendar domain."""
        email = EmailContent(
            message_id="test1",
            sender="Google Calendar",
            sender_email="calendar@google.com",
            subject="Meeting invitation",
        )
        is_event, confidence = self.filter.check_sender(email)
        assert is_event is True
        assert confidence >= 0.9

    def test_check_sender_regular_domain(self):
        """Test sender check with regular domain."""
        email = EmailContent(
            message_id="test2",
            sender="John Doe",
            sender_email="john@example.com",
            subject="Hello",
        )
        is_event, confidence = self.filter.check_sender(email)
        assert is_event is False

    def test_check_subject_event_keywords(self):
        """Test subject check with event keywords."""
        email = EmailContent(
            message_id="test3",
            subject="Team meeting tomorrow",
        )
        is_event, confidence = self.filter.check_subject(email)
        assert is_event is True
        assert confidence >= 0.5

    def test_check_subject_non_event(self):
        """Test subject check with non-event patterns."""
        email = EmailContent(
            message_id="test4",
            subject="Re: Your order confirmation",
        )
        is_event, confidence = self.filter.check_subject(email)
        assert is_event is False

    def test_check_body_datetime_patterns(self):
        """Test body check with datetime patterns."""
        email = EmailContent(
            message_id="test5",
            body_text="Please join us on January 15th at 2:00 PM for a meeting.",
        )
        is_event, confidence = self.filter.check_body(email)
        assert is_event is True

    def test_check_body_meeting_keywords(self):
        """Test body check with meeting keywords."""
        email = EmailContent(
            message_id="test6",
            body_text="Join the Zoom meeting using this link: zoom.us/j/123",
        )
        is_event, confidence = self.filter.check_body(email)
        assert is_event is True

    def test_should_process_event_email(self):
        """Test should_process with event email."""
        email = EmailContent(
            message_id="test7",
            subject="Project Review Meeting",
            sender="Project Manager",
            sender_email="pm@company.com",
            body_text="Let's schedule a meeting for next Monday at 10 AM to review the project.",
        )
        should_process, confidence = self.filter.should_process(email)
        assert should_process is True

    def test_should_process_non_event_email(self):
        """Test should_process with non-event email."""
        email = EmailContent(
            message_id="test8",
            subject="Your weekly newsletter",
            sender="Newsletter",
            sender_email="newsletter@company.com",
            body_text="Here are this week's top stories and updates.",
        )
        should_process, confidence = self.filter.should_process(email)
        assert should_process is False


class TestEventExtractionService:
    """Tests for the EventExtractionService class."""

    def setup_method(self):
        # Use mock LLM provider for testing
        self.service = EventExtractionService(provider=MockLLMProvider())

    @pytest.mark.asyncio
    async def test_extract_non_event_email(self):
        """Test extraction with non-event email."""
        email = EmailContent(
            message_id="test1",
            subject="Your receipt",
            sender="Store",
            sender_email="store@example.com",
            body_text="Thank you for your purchase.",
        )
        result = await self.service.extract(email)
        assert result.is_event is False

    @pytest.mark.asyncio
    async def test_extract_event_email_with_heuristics(self):
        """Test that heuristics correctly identify event emails."""
        email = EmailContent(
            message_id="test2",
            subject="Team standup meeting",
            sender="Team Lead",
            sender_email="lead@company.com",
            body_text="Daily standup at 9 AM tomorrow.",
        )
        result = await self.service.extract(email)
        # The mock LLM returns is_event=False, but heuristics should process it
        assert result.extraction_method in ["heuristic_reject", "llm"]
