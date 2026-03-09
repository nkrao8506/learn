"""
Settings API routes.
"""
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import get_client_ip
from app.auth.dependencies import get_current_user
from app.models.models import User, UserSettings, Filter, AuditLog
from app.models.schemas import (
    UserSettingsResponse,
    UserSettingsUpdate,
    FilterCreate,
    FilterResponse,
    FilterListResponse,
)

router = APIRouter(prefix="/api/settings", tags=["Settings"])


@router.get("", response_model=UserSettingsResponse)
async def get_settings(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get current user's settings.
    """
    query = select(UserSettings).where(UserSettings.user_id == user.id)
    result = await db.execute(query)
    settings = result.scalar_one_or_none()
    
    if not settings:
        # Create default settings
        settings = UserSettings(user_id=user.id)
        db.add(settings)
        await db.commit()
        await db.refresh(settings)
    
    return UserSettingsResponse.model_validate(settings)


@router.put("", response_model=UserSettingsResponse)
async def update_settings(
    settings_update: UserSettingsUpdate,
    request: Request = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Update user's settings.
    """
    query = select(UserSettings).where(UserSettings.user_id == user.id)
    result = await db.execute(query)
    settings = result.scalar_one_or_none()
    
    if not settings:
        settings = UserSettings(user_id=user.id)
        db.add(settings)
    
    # Update fields
    update_data = settings_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(settings, field, value)
    
    # Log the action
    audit_log = AuditLog(
        user_id=user.id,
        action="settings_update",
        resource_type="settings",
        ip_address=get_client_ip(request) if request else None,
        details={"fields_updated": list(update_data.keys())},
    )
    db.add(audit_log)
    await db.commit()
    
    return UserSettingsResponse.model_validate(settings)


# Filter routes
@router.get("/filters", response_model=FilterListResponse)
async def list_filters(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    List all filters for the current user.
    """
    query = select(Filter).where(Filter.user_id == user.id).order_by(Filter.created_at.desc())
    result = await db.execute(query)
    filters = result.scalars().all()
    
    return FilterListResponse(
        filters=[FilterResponse.model_validate(f) for f in filters],
        total=len(filters),
    )


@router.post("/filters", response_model=FilterResponse, status_code=status.HTTP_201_CREATED)
async def create_filter(
    filter_create: FilterCreate,
    request: Request = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new filter.
    Filters can be used to include or exclude emails from specific senders or with specific labels.
    """
    # Check if filter already exists
    query = select(Filter).where(
        Filter.user_id == user.id,
        Filter.filter_type == filter_create.filter_type.value,
        Filter.filter_value == filter_create.filter_value.lower(),
    )
    result = await db.execute(query)
    existing = result.scalar_one_or_none()
    
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filter already exists"
        )
    
    # Create filter
    new_filter = Filter(
        user_id=user.id,
        filter_type=filter_create.filter_type.value,
        filter_value=filter_create.filter_value.lower(),
        action=filter_create.action.value,
    )
    db.add(new_filter)
    
    # Log the action
    audit_log = AuditLog(
        user_id=user.id,
        action="filter_create",
        resource_type="filter",
        ip_address=get_client_ip(request) if request else None,
        details={
            "filter_type": filter_create.filter_type.value,
            "filter_value": filter_create.filter_value.lower(),
            "action": filter_create.action.value,
        },
    )
    db.add(audit_log)
    await db.commit()
    
    return FilterResponse.model_validate(new_filter)


@router.delete("/filters/{filter_id}")
async def delete_filter(
    filter_id: str,
    request: Request = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete a filter.
    """
    query = select(Filter).where(
        Filter.id == filter_id,
        Filter.user_id == user.id
    )
    result = await db.execute(query)
    filter_obj = result.scalar_one_or_none()
    
    if not filter_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Filter not found"
        )
    
    # Log before deletion
    audit_log = AuditLog(
        user_id=user.id,
        action="filter_delete",
        resource_type="filter",
        resource_id=filter_obj.id,
        ip_address=get_client_ip(request) if request else None,
        details={
            "filter_type": filter_obj.filter_type,
            "filter_value": filter_obj.filter_value,
        },
    )
    db.add(audit_log)
    
    await db.delete(filter_obj)
    await db.commit()
    
    return {"message": "Filter deleted", "filter_id": filter_id}
