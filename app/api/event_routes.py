"""
Event management API routes.
"""
from typing import Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_
import math

from app.core.database import get_db
from app.core.security import get_client_ip
from app.auth.dependencies import get_current_user
from app.models.models import User, Event, AuditLog, EventStatus
from app.models.schemas import (
    EventResponse,
    EventListResponse,
    EventUpdate,
    EventAcceptResponse,
    ErrorResponse,
)
from app.calendar.calendar_service import CalendarSyncService

router = APIRouter(prefix="/api/events", tags=["Events"])


@router.get("", response_model=EventListResponse)
async def list_events(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    status: Optional[str] = Query(None, description="Filter by status"),
    start_date: Optional[datetime] = Query(None, description="Filter events starting after this date"),
    end_date: Optional[datetime] = Query(None, description="Filter events starting before this date"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    List all events for the current user.
    Supports pagination and filtering by status and date range.
    """
    # Build query
    query = select(Event).where(Event.user_id == user.id)
    count_query = select(func.count(Event.id)).where(Event.user_id == user.id)
    
    # Apply filters
    if status:
        query = query.where(Event.status == status)
        count_query = count_query.where(Event.status == status)
    
    if start_date:
        query = query.where(Event.start_datetime >= start_date)
        count_query = count_query.where(Event.start_datetime >= start_date)
    
    if end_date:
        query = query.where(Event.start_datetime <= end_date)
        count_query = count_query.where(Event.start_datetime <= end_date)
    
    # Get total count
    total_result = await db.execute(count_query)
    total = total_result.scalar()
    
    # Apply pagination
    offset = (page - 1) * page_size
    query = query.order_by(Event.start_datetime.asc()).offset(offset).limit(page_size)
    
    # Execute query
    result = await db.execute(query)
    events = result.scalars().all()
    
    # Calculate total pages
    pages = math.ceil(total / page_size) if total > 0 else 1
    
    return EventListResponse(
        events=[EventResponse.model_validate(e) for e in events],
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


@router.get("/{event_id}", response_model=EventResponse)
async def get_event(
    event_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get details of a specific event.
    """
    query = select(Event).where(
        Event.id == event_id,
        Event.user_id == user.id
    )
    result = await db.execute(query)
    event = result.scalar_one_or_none()
    
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found"
        )
    
    return EventResponse.model_validate(event)


@router.post("/{event_id}/accept", response_model=EventAcceptResponse)
async def accept_event(
    event_id: str,
    request: Request = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Accept a proposed event.
    Creates the event in Google Calendar.
    """
    # Get event
    query = select(Event).where(
        Event.id == event_id,
        Event.user_id == user.id
    )
    result = await db.execute(query)
    event = result.scalar_one_or_none()
    
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found"
        )
    
    if event.status not in [EventStatus.PROPOSED.value, EventStatus.REJECTED.value]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Event is already {event.status}"
        )
    
    # Accept event and sync to calendar
    try:
        sync_service = CalendarSyncService(db)
        updated_event = await sync_service.accept_proposed_event(event_id, str(user.id))
        await db.commit()
        
        # Log the action
        audit_log = AuditLog(
            user_id=user.id,
            action="event_accept",
            resource_type="event",
            resource_id=updated_event.id,
            ip_address=get_client_ip(request) if request else None,
            details={"calendar_event_id": updated_event.calendar_event_id},
        )
        db.add(audit_log)
        await db.commit()
        
        # Generate calendar link
        calendar_link = None
        if updated_event.calendar_event_id:
            calendar_link = f"https://calendar.google.com/calendar/event?eid={updated_event.calendar_event_id}"
        
        return EventAcceptResponse(
            event=EventResponse.model_validate(updated_event),
            calendar_event_id=updated_event.calendar_event_id,
            calendar_link=calendar_link,
        )
        
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to accept event: {str(e)}"
        )


@router.post("/{event_id}/reject")
async def reject_event(
    event_id: str,
    request: Request = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Reject a proposed event.
    Removes the event from Google Calendar if already created.
    """
    # Get event
    query = select(Event).where(
        Event.id == event_id,
        Event.user_id == user.id
    )
    result = await db.execute(query)
    event = result.scalar_one_or_none()
    
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found"
        )
    
    if event.status == EventStatus.REJECTED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Event is already rejected"
        )
    
    # Reject event
    try:
        sync_service = CalendarSyncService(db)
        updated_event = await sync_service.reject_proposed_event(event_id, str(user.id))
        await db.commit()
        
        # Log the action
        audit_log = AuditLog(
            user_id=user.id,
            action="event_reject",
            resource_type="event",
            resource_id=updated_event.id,
            ip_address=get_client_ip(request) if request else None,
        )
        db.add(audit_log)
        await db.commit()
        
        return {"message": "Event rejected", "event_id": event_id}
        
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reject event: {str(e)}"
        )


@router.put("/{event_id}", response_model=EventResponse)
async def update_event(
    event_id: str,
    event_update: EventUpdate,
    request: Request = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Update an event before accepting.
    Can modify title, description, times, location, etc.
    """
    # Get event
    query = select(Event).where(
        Event.id == event_id,
        Event.user_id == user.id
    )
    result = await db.execute(query)
    event = result.scalar_one_or_none()
    
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found"
        )
    
    # Update fields
    update_data = event_update.model_dump(exclude_unset=True)
    
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update"
        )
    
    for field, value in update_data.items():
        setattr(event, field, value)
    
    # If event is already synced, update in calendar too
    if event.calendar_event_id:
        try:
            sync_service = CalendarSyncService(db)
            await sync_service.update_calendar_event(event, str(user.id))
        except Exception as e:
            # Log error but don't fail
            pass
    
    # Log the action
    audit_log = AuditLog(
        user_id=user.id,
        action="event_update",
        resource_type="event",
        resource_id=event.id,
        ip_address=get_client_ip(request) if request else None,
        details={"fields_updated": list(update_data.keys())},
    )
    db.add(audit_log)
    await db.commit()
    
    return EventResponse.model_validate(event)


@router.delete("/{event_id}")
async def delete_event(
    event_id: str,
    request: Request = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete an event.
    Removes from Google Calendar if synced.
    """
    # Get event
    query = select(Event).where(
        Event.id == event_id,
        Event.user_id == user.id
    )
    result = await db.execute(query)
    event = result.scalar_one_or_none()
    
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found"
        )
    
    # Delete from calendar if synced
    if event.calendar_event_id:
        try:
            sync_service = CalendarSyncService(db)
            await sync_service.delete_calendar_event(event, str(user.id))
        except Exception as e:
            # Log error but continue with deletion
            pass
    
    # Log before deletion
    audit_log = AuditLog(
        user_id=user.id,
        action="event_delete",
        resource_type="event",
        resource_id=event.id,
        ip_address=get_client_ip(request) if request else None,
        details={"title": event.title, "calendar_event_id": event.calendar_event_id},
    )
    db.add(audit_log)
    
    # Delete event
    await db.delete(event)
    await db.commit()
    
    return {"message": "Event deleted", "event_id": event_id}
