"""
Webhook API routes for Gmail notifications and polling.
"""
import json
import base64
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status, Request, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import logging

from app.core.config import settings
from app.core.database import get_db
from app.auth.dependencies import get_current_user
from app.models.models import User, UserSettings, GmailWatch, Event, EventStatus
from app.gmail.gmail_service import GmailService
from app.events.extraction import EventExtractionService
from app.calendar.calendar_service import CalendarSyncService

router = APIRouter(tags=["Webhooks"])
logger = logging.getLogger(__name__)


async def process_user_emails(user_id: str, db: AsyncSession):
    """
    Background task to process new emails for a user.
    This is the main email processing pipeline.
    """
    logger.info(f"Starting email processing for user {user_id}")
    
    try:
        gmail_service = GmailService(db)
        extraction_service = EventExtractionService()
        calendar_sync = CalendarSyncService(db)
        
        # Get user settings
        settings_query = select(UserSettings).where(UserSettings.user_id == user_id)
        settings_result = await db.execute(settings_query)
        user_settings = settings_result.scalar_one_or_none()
        
        # Get unprocessed messages
        message_ids = await gmail_service.get_unprocessed_messages(
            user_id=user_id,
            since_days=settings.GMAIL_HISTORY_LOOKUP_DAYS,
            max_messages=settings.GMAIL_MAX_MESSAGES_PER_POLL
        )
        
        logger.info(f"Found {len(message_ids)} unprocessed messages for user {user_id}")
        
        processed_count = 0
        events_created = 0
        
        for message_id in message_ids:
            try:
                # Extract email content
                email_content = await gmail_service.extract_email_content(user_id, message_id)
                
                if not email_content:
                    await gmail_service.mark_message_processed(
                        user_id=user_id,
                        message_id=message_id,
                        result="error",
                        error_message="Failed to extract email content"
                    )
                    continue
                
                # Extract event information
                extraction_result = await extraction_service.extract(email_content)
                
                if extraction_result.is_event and extraction_result.event:
                    # Create event record
                    event = Event(
                        user_id=user_id,
                        title=extraction_result.event.title,
                        description=extraction_result.event.description,
                        start_datetime=extraction_result.event.start_datetime,
                        end_datetime=extraction_result.event.end_datetime,
                        timezone=extraction_result.event.timezone,
                        location=extraction_result.event.location,
                        importance_score=extraction_result.event.importance_score,
                        confidence_score=extraction_result.event.confidence_score,
                        source_email_id=message_id,
                        source_email_subject=email_content.subject,
                        source_email_sender=email_content.sender_email,
                        status=EventStatus.PROPOSED.value,
                    )
                    db.add(event)
                    await db.flush()
                    
                    # Check if auto-add is enabled and confidence is high enough
                    if (user_settings and user_settings.auto_add_events and
                        extraction_result.event.confidence_score >= user_settings.min_confidence_threshold):
                        
                        # Create in calendar
                        try:
                            await calendar_sync.create_calendar_event(event, user_id)
                            event.status = EventStatus.AUTO_CREATED.value
                            events_created += 1
                            logger.info(f"Auto-created calendar event for message {message_id}")
                        except Exception as e:
                            logger.error(f"Failed to auto-create calendar event: {e}")
                    
                    # Mark message as processed
                    await gmail_service.mark_message_processed(
                        user_id=user_id,
                        message_id=message_id,
                        thread_id=email_content.labels[0] if email_content.labels else None,
                        result="event_created"
                    )
                    events_created += 1
                else:
                    # No event found
                    await gmail_service.mark_message_processed(
                        user_id=user_id,
                        message_id=message_id,
                        result="no_event"
                    )
                
                processed_count += 1
                
            except Exception as e:
                logger.error(f"Error processing message {message_id}: {e}")
                await gmail_service.mark_message_processed(
                    user_id=user_id,
                    message_id=message_id,
                    result="error",
                    error_message=str(e)
                )
        
        await db.commit()
        logger.info(f"Processed {processed_count} messages, created {events_created} events for user {user_id}")
        
    except Exception as e:
        logger.error(f"Error in email processing for user {user_id}: {e}")
        await db.rollback()


@router.post("/webhook/gmail")
async def gmail_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    Handle Gmail Pub/Sub push notifications.
    This endpoint receives notifications when new emails arrive.
    """
    try:
        body = await request.json()
        
        # Pub/Sub message format
        if "message" not in body:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid Pub/Sub message format"
            )
        
        # Decode the message
        message = body["message"]
        data = message.get("data", "")
        
        if data:
            decoded_data = base64.b64decode(data).decode("utf-8")
            notification = json.loads(decoded_data)
            
            # Extract email address from notification
            email_address = notification.get("emailAddress")
            history_id = notification.get("historyId")
            
            if not email_address:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="No email address in notification"
                )
            
            # Find user by email
            user_query = select(User).where(User.email == email_address, User.is_active == True)
            user_result = await db.execute(user_query)
            user = user_result.scalar_one_or_none()
            
            if not user:
                logger.warning(f"No active user found for email: {email_address}")
                return {"status": "ignored", "reason": "User not found"}
            
            # Update watch history ID
            watch_query = select(GmailWatch).where(GmailWatch.user_id == user.id)
            watch_result = await db.execute(watch_query)
            watch = watch_result.scalar_one_or_none()
            
            if watch:
                watch.history_id = history_id
            else:
                watch = GmailWatch(
                    user_id=user.id,
                    history_id=history_id
                )
                db.add(watch)
            
            await db.commit()
            
            # Trigger background processing
            background_tasks.add_task(process_user_emails, str(user.id), db)
            
            logger.info(f"Gmail notification processed for user {user.id}")
            
            return {"status": "processed", "user_id": str(user.id)}
        
        return {"status": "ignored", "reason": "No data in message"}
        
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON in request body"
        )
    except Exception as e:
        logger.error(f"Error processing Gmail webhook: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/webhook/gmail/renew")
async def renew_gmail_watch(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Renew Gmail watch subscription.
    Gmail watches expire after about 7 days and need to be renewed.
    """
    if not settings.GOOGLE_PUB_SUB_TOPIC:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Pub/Sub is not configured"
        )
    
    try:
        gmail_service = GmailService(db)
        result = await gmail_service.setup_watch(
            user_id=str(user.id),
            topic_name=settings.GOOGLE_PUB_SUB_TOPIC
        )
        
        # Store watch info
        watch_query = select(GmailWatch).where(GmailWatch.user_id == user.id)
        watch_result = await db.execute(watch_query)
        watch = watch_result.scalar_one_or_none()
        
        history_id = int(result.get("historyId", 0))
        expiration = result.get("expiration")
        
        if watch:
            watch.history_id = history_id
            if expiration:
                watch.expiration = datetime.fromtimestamp(int(expiration) / 1000)
        else:
            watch = GmailWatch(
                user_id=user.id,
                history_id=history_id,
                expiration=datetime.fromtimestamp(int(expiration) / 1000) if expiration else None
            )
            db.add(watch)
        
        await db.commit()
        
        return {
            "status": "success",
            "history_id": history_id,
            "expiration": expiration
        }
        
    except Exception as e:
        logger.error(f"Failed to renew Gmail watch: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to renew watch: {str(e)}"
        )


@router.post("/api/emails/process")
async def trigger_email_processing(
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Manually trigger email processing for the current user.
    Useful for testing or when notifications are not working.
    """
    # Run processing in background
    background_tasks.add_task(process_user_emails, str(user.id), db)
    
    return {
        "status": "processing_started",
        "user_id": str(user.id),
        "message": "Email processing started in background"
    }


@router.get("/api/emails/status")
async def get_email_processing_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get email processing status for the current user.
    """
    from sqlalchemy import func
    from app.models.models import ProcessedMessage
    
    # Get stats
    total_query = select(func.count(ProcessedMessage.id)).where(
        ProcessedMessage.user_id == user.id
    )
    total_result = await db.execute(total_query)
    total_processed = total_result.scalar() or 0
    
    events_query = select(func.count(ProcessedMessage.id)).where(
        ProcessedMessage.user_id == user.id,
        ProcessedMessage.result == "event_created"
    )
    events_result = await db.execute(events_query)
    events_created = events_result.scalar() or 0
    
    errors_query = select(func.count(ProcessedMessage.id)).where(
        ProcessedMessage.user_id == user.id,
        ProcessedMessage.result == "error"
    )
    errors_result = await db.execute(errors_query)
    errors = errors_result.scalar() or 0
    
    # Get watch status
    watch_query = select(GmailWatch).where(GmailWatch.user_id == user.id)
    watch_result = await db.execute(watch_query)
    watch = watch_result.scalar_one_or_none()
    
    return {
        "total_processed": total_processed,
        "events_created": events_created,
        "errors": errors,
        "watch_status": {
            "active": watch is not None,
            "history_id": watch.history_id if watch else None,
            "expiration": watch.expiration.isoformat() if watch and watch.expiration else None,
        } if watch else None
    }
