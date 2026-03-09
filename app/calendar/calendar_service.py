"""
Google Calendar API integration service.
"""
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.core.config import settings
from app.core.security import token_encryption
from app.models.models import User, OAuthToken, Event, EventStatus
from app.models.schemas import EventCandidate
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select


class CalendarError(Exception):
    """Exception for Calendar API errors."""
    pass


class GoogleCalendarService:
    """Service for interacting with Google Calendar API."""

    def __init__(self, db: AsyncSession):
        self.db = db

    def _create_credentials(self, access_token: str, refresh_token: str = None) -> Credentials:
        """Create Google OAuth credentials object."""
        return Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=settings.GOOGLE_CLIENT_ID,
            client_secret=settings.GOOGLE_CLIENT_SECRET,
            scopes=settings.GOOGLE_SCOPES,
        )

    async def _get_service(self, user_id: str):
        """Get Calendar service for a user."""
        # Get user's tokens
        stmt = select(OAuthToken).where(OAuthToken.user_id == user_id)
        result = await self.db.execute(stmt)
        token_record = result.scalar_one_or_none()

        if not token_record:
            raise CalendarError("No OAuth tokens found for user")

        # Decrypt tokens
        access_token = token_encryption.decrypt(token_record.access_token)
        refresh_token = token_encryption.decrypt(token_record.refresh_token)

        # Create credentials
        credentials = self._create_credentials(access_token, refresh_token)

        # Build service
        service = build('calendar', 'v3', credentials=credentials)
        return service

    async def create_event(
        self,
        user_id: str,
        event: EventCandidate,
        calendar_id: str = 'primary'
    ) -> Dict[str, Any]:
        """
        Create an event in Google Calendar.
        Returns the created event data with ID.
        """
        service = await self._get_service(user_id)
        
        # Build event body
        event_body = {
            'summary': event.title,
            'description': event.description or '',
            'start': {
                'dateTime': event.start_datetime.isoformat(),
                'timeZone': event.timezone,
            },
            'end': {
                'dateTime': (event.end_datetime or event.start_datetime + timedelta(hours=1)).isoformat(),
                'timeZone': event.timezone,
            },
        }
        
        # Add location if provided
        if event.location:
            event_body['location'] = event.location
        
        # Add reminders
        event_body['reminders'] = {
            'useDefault': False,
            'overrides': [
                {'method': 'email', 'minutes': 24 * 60},  # 1 day before
                {'method': 'popup', 'minutes': 30},  # 30 minutes before
            ],
        }
        
        try:
            created_event = service.events().insert(
                calendarId=calendar_id,
                body=event_body
            ).execute()
            
            return created_event
        except HttpError as e:
            raise CalendarError(f"Failed to create event: {e}")

    async def update_event(
        self,
        user_id: str,
        calendar_event_id: str,
        event: EventCandidate,
        calendar_id: str = 'primary'
    ) -> Dict[str, Any]:
        """
        Update an existing event in Google Calendar.
        """
        service = await self._get_service(user_id)
        
        # First, get the existing event
        try:
            existing_event = service.events().get(
                calendarId=calendar_id,
                eventId=calendar_event_id
            ).execute()
        except HttpError as e:
            raise CalendarError(f"Failed to get event: {e}")
        
        # Update fields
        existing_event['summary'] = event.title
        if event.description:
            existing_event['description'] = event.description
        existing_event['start'] = {
            'dateTime': event.start_datetime.isoformat(),
            'timeZone': event.timezone,
        }
        existing_event['end'] = {
            'dateTime': (event.end_datetime or event.start_datetime + timedelta(hours=1)).isoformat(),
            'timeZone': event.timezone,
        }
        if event.location:
            existing_event['location'] = event.location
        
        try:
            updated_event = service.events().update(
                calendarId=calendar_id,
                eventId=calendar_event_id,
                body=existing_event
            ).execute()
            
            return updated_event
        except HttpError as e:
            raise CalendarError(f"Failed to update event: {e}")

    async def delete_event(
        self,
        user_id: str,
        calendar_event_id: str,
        calendar_id: str = 'primary'
    ) -> bool:
        """
        Delete an event from Google Calendar.
        """
        service = await self._get_service(user_id)
        
        try:
            service.events().delete(
                calendarId=calendar_id,
                eventId=calendar_event_id
            ).execute()
            return True
        except HttpError as e:
            if e.resp.status == 410:
                # Event already deleted
                return True
            raise CalendarError(f"Failed to delete event: {e}")

    async def get_event(
        self,
        user_id: str,
        calendar_event_id: str,
        calendar_id: str = 'primary'
    ) -> Optional[Dict[str, Any]]:
        """
        Get an event from Google Calendar.
        """
        service = await self._get_service(user_id)
        
        try:
            event = service.events().get(
                calendarId=calendar_id,
                eventId=calendar_event_id
            ).execute()
            return event
        except HttpError as e:
            if e.resp.status == 404:
                return None
            raise CalendarError(f"Failed to get event: {e}")

    async def list_events(
        self,
        user_id: str,
        time_min: datetime = None,
        time_max: datetime = None,
        max_results: int = 100,
        calendar_id: str = 'primary'
    ) -> List[Dict[str, Any]]:
        """
        List events from Google Calendar.
        """
        service = await self._get_service(user_id)
        
        if time_min is None:
            time_min = datetime.utcnow()
        if time_max is None:
            time_max = time_min + timedelta(days=30)
        
        try:
            events_result = service.events().list(
                calendarId=calendar_id,
                timeMin=time_min.isoformat() + 'Z',
                timeMax=time_max.isoformat() + 'Z',
                maxResults=max_results,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            return events_result.get('items', [])
        except HttpError as e:
            raise CalendarError(f"Failed to list events: {e}")

    async def check_event_exists(
        self,
        user_id: str,
        calendar_event_id: str,
        calendar_id: str = 'primary'
    ) -> bool:
        """Check if an event exists in Google Calendar."""
        event = await self.get_event(user_id, calendar_event_id, calendar_id)
        return event is not None


class CalendarSyncService:
    """Service for syncing events between our database and Google Calendar."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.calendar_service = GoogleCalendarService(db)

    async def create_calendar_event(
        self,
        event_record: Event,
        user_id: str
    ) -> Event:
        """
        Create a calendar event from our Event record.
        Updates the Event record with the calendar event ID.
        """
        # Create event candidate from our record
        candidate = EventCandidate(
            title=event_record.title,
            description=event_record.description,
            start_datetime=event_record.start_datetime,
            end_datetime=event_record.end_datetime,
            timezone=event_record.timezone,
            location=event_record.location,
            importance_score=event_record.importance_score,
            confidence_score=event_record.confidence_score,
        )
        
        # Create in Google Calendar
        calendar_event = await self.calendar_service.create_event(
            user_id=user_id,
            event=candidate
        )
        
        # Update our record
        event_record.calendar_event_id = calendar_event['id']
        event_record.calendar_synced_at = datetime.utcnow()
        event_record.status = EventStatus.ACCEPTED.value
        
        await self.db.flush()
        return event_record

    async def update_calendar_event(
        self,
        event_record: Event,
        user_id: str
    ) -> Event:
        """
        Update a calendar event from our Event record.
        """
        if not event_record.calendar_event_id:
            return await self.create_calendar_event(event_record, user_id)
        
        # Create event candidate from our record
        candidate = EventCandidate(
            title=event_record.title,
            description=event_record.description,
            start_datetime=event_record.start_datetime,
            end_datetime=event_record.end_datetime,
            timezone=event_record.timezone,
            location=event_record.location,
            importance_score=event_record.importance_score,
            confidence_score=event_record.confidence_score,
        )
        
        # Update in Google Calendar
        await self.calendar_service.update_event(
            user_id=user_id,
            calendar_event_id=event_record.calendar_event_id,
            event=candidate
        )
        
        event_record.calendar_synced_at = datetime.utcnow()
        await self.db.flush()
        return event_record

    async def delete_calendar_event(
        self,
        event_record: Event,
        user_id: str
    ) -> bool:
        """
        Delete a calendar event.
        """
        if not event_record.calendar_event_id:
            return True
        
        result = await self.calendar_service.delete_event(
            user_id=user_id,
            calendar_event_id=event_record.calendar_event_id
        )
        
        event_record.calendar_event_id = None
        event_record.calendar_synced_at = None
        event_record.status = EventStatus.REJECTED.value
        
        await self.db.flush()
        return result

    async def accept_proposed_event(
        self,
        event_id: str,
        user_id: str
    ) -> Event:
        """
        Accept a proposed event and create it in Google Calendar.
        """
        # Get event from database
        stmt = select(Event).where(
            Event.id == event_id,
            Event.user_id == user_id
        )
        result = await self.db.execute(stmt)
        event = result.scalar_one_or_none()
        
        if not event:
            raise CalendarError("Event not found")
        
        if event.status != EventStatus.PROPOSED.value:
            raise CalendarError(f"Event is not in proposed status: {event.status}")
        
        return await self.create_calendar_event(event, user_id)

    async def reject_proposed_event(
        self,
        event_id: str,
        user_id: str
    ) -> Event:
        """
        Reject a proposed event.
        """
        stmt = select(Event).where(
            Event.id == event_id,
            Event.user_id == user_id
        )
        result = await self.db.execute(stmt)
        event = result.scalar_one_or_none()
        
        if not event:
            raise CalendarError("Event not found")
        
        # If already synced, delete from calendar
        if event.calendar_event_id:
            await self.calendar_service.delete_event(user_id, event.calendar_event_id)
        
        event.status = EventStatus.REJECTED.value
        await self.db.flush()
        return event
