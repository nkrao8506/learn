"""
Tests for API endpoints.
"""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import User, Event, EventStatus
from app.core.security import JWTHandler
import uuid
from datetime import datetime, timedelta


@pytest.mark.asyncio
class TestHealthEndpoint:
    """Tests for health check endpoint."""

    async def test_health_check(self, client: AsyncClient):
        """Test health check returns healthy status."""
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data


@pytest.mark.asyncio
class TestAuthEndpoints:
    """Tests for authentication endpoints."""

    async def test_auth_status_unauthenticated(self, client: AsyncClient):
        """Test auth status when not authenticated."""
        response = await client.get("/auth/status")
        assert response.status_code == 200
        data = response.json()
        assert data["authenticated"] is False

    async def test_auth_status_authenticated(
        self,
        client: AsyncClient,
        test_user: User,
        auth_headers: dict
    ):
        """Test auth status when authenticated."""
        response = await client.get("/auth/status", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["authenticated"] is True
        assert data["email"] == test_user.email

    async def test_get_current_user_unauthenticated(self, client: AsyncClient):
        """Test getting current user without authentication."""
        response = await client.get("/auth/me")
        assert response.status_code == 401

    async def test_get_current_user_authenticated(
        self,
        client: AsyncClient,
        test_user: User,
        auth_headers: dict
    ):
        """Test getting current user with authentication."""
        response = await client.get("/auth/me", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == test_user.email
        assert data["name"] == test_user.name


@pytest.mark.asyncio
class TestEventEndpoints:
    """Tests for event endpoints."""

    async def test_list_events_empty(
        self,
        client: AsyncClient,
        auth_headers: dict
    ):
        """Test listing events when none exist."""
        response = await client.get("/api/events", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["events"] == []

    async def test_list_events_unauthenticated(self, client: AsyncClient):
        """Test listing events without authentication."""
        response = await client.get("/api/events")
        assert response.status_code == 401

    async def test_create_and_list_events(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict
    ):
        """Test creating and listing events."""
        # Create an event directly in database
        event = Event(
            id=uuid.uuid4(),
            user_id=test_user.id,
            title="Test Event",
            description="Test description",
            start_datetime=datetime.utcnow() + timedelta(days=1),
            end_datetime=datetime.utcnow() + timedelta(days=1, hours=1),
            timezone="UTC",
            source_email_id="test_email_id",
            status=EventStatus.PROPOSED.value,
        )
        db_session.add(event)
        await db_session.commit()

        # List events
        response = await client.get("/api/events", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["events"]) == 1
        assert data["events"][0]["title"] == "Test Event"

    async def test_get_event_by_id(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict
    ):
        """Test getting a specific event by ID."""
        # Create an event
        event = Event(
            id=uuid.uuid4(),
            user_id=test_user.id,
            title="Specific Event",
            start_datetime=datetime.utcnow() + timedelta(days=1),
            timezone="UTC",
            source_email_id="test_email_id_2",
            status=EventStatus.PROPOSED.value,
        )
        db_session.add(event)
        await db_session.commit()

        # Get the event
        response = await client.get(f"/api/events/{event.id}", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Specific Event"

    async def test_get_nonexistent_event(self, client: AsyncClient, auth_headers: dict):
        """Test getting a non-existent event."""
        fake_id = str(uuid.uuid4())
        response = await client.get(f"/api/events/{fake_id}", headers=auth_headers)
        assert response.status_code == 404

    async def test_update_event(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict
    ):
        """Test updating an event."""
        # Create an event
        event = Event(
            id=uuid.uuid4(),
            user_id=test_user.id,
            title="Original Title",
            start_datetime=datetime.utcnow() + timedelta(days=1),
            timezone="UTC",
            source_email_id="test_email_id_3",
            status=EventStatus.PROPOSED.value,
        )
        db_session.add(event)
        await db_session.commit()

        # Update the event
        response = await client.put(
            f"/api/events/{event.id}",
            headers=auth_headers,
            json={"title": "Updated Title"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Updated Title"

    async def test_delete_event(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict
    ):
        """Test deleting an event."""
        # Create an event
        event = Event(
            id=uuid.uuid4(),
            user_id=test_user.id,
            title="Event to Delete",
            start_datetime=datetime.utcnow() + timedelta(days=1),
            timezone="UTC",
            source_email_id="test_email_id_4",
            status=EventStatus.PROPOSED.value,
        )
        db_session.add(event)
        await db_session.commit()
        event_id = event.id

        # Delete the event
        response = await client.delete(f"/api/events/{event_id}", headers=auth_headers)
        assert response.status_code == 200

        # Verify it's deleted
        response = await client.get(f"/api/events/{event_id}", headers=auth_headers)
        assert response.status_code == 404


@pytest.mark.asyncio
class TestSettingsEndpoints:
    """Tests for settings endpoints."""

    async def test_get_settings(
        self,
        client: AsyncClient,
        auth_headers: dict
    ):
        """Test getting user settings."""
        response = await client.get("/api/settings", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "auto_add_events" in data
        assert "min_confidence_threshold" in data
        assert "timezone" in data

    async def test_update_settings(
        self,
        client: AsyncClient,
        auth_headers: dict
    ):
        """Test updating user settings."""
        response = await client.put(
            "/api/settings",
            headers=auth_headers,
            json={"auto_add_events": True, "timezone": "America/New_York"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["auto_add_events"] is True
        assert data["timezone"] == "America/New_York"

    async def test_list_filters_empty(
        self,
        client: AsyncClient,
        auth_headers: dict
    ):
        """Test listing filters when none exist."""
        response = await client.get("/api/settings/filters", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0

    async def test_create_and_delete_filter(
        self,
        client: AsyncClient,
        auth_headers: dict
    ):
        """Test creating and deleting a filter."""
        # Create filter
        response = await client.post(
            "/api/settings/filters",
            headers=auth_headers,
            json={
                "filter_type": "sender",
                "filter_value": "newsletter@example.com",
                "action": "exclude"
            }
        )
        assert response.status_code == 201
        data = response.json()
        assert data["filter_value"] == "newsletter@example.com"
        filter_id = data["id"]

        # List filters
        response = await client.get("/api/settings/filters", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["total"] == 1

        # Delete filter
        response = await client.delete(f"/api/settings/filters/{filter_id}", headers=auth_headers)
        assert response.status_code == 200

        # Verify deleted
        response = await client.get("/api/settings/filters", headers=auth_headers)
        assert response.json()["total"] == 0


@pytest.mark.asyncio
class TestPagination:
    """Tests for pagination."""

    async def test_event_pagination(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict
    ):
        """Test event list pagination."""
        # Create multiple events
        for i in range(25):
            event = Event(
                id=uuid.uuid4(),
                user_id=test_user.id,
                title=f"Event {i}",
                start_datetime=datetime.utcnow() + timedelta(days=i),
                timezone="UTC",
                source_email_id=f"email_{i}",
                status=EventStatus.PROPOSED.value,
            )
            db_session.add(event)
        await db_session.commit()

        # Get first page
        response = await client.get("/api/events?page=1&page_size=10", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 1
        assert data["page_size"] == 10
        assert len(data["events"]) == 10
        assert data["total"] == 25
        assert data["pages"] == 3

        # Get second page
        response = await client.get("/api/events?page=2&page_size=10", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 2
        assert len(data["events"]) == 10
