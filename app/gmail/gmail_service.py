"""
Gmail API integration service.
"""
import base64
import email
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timedelta
from email.utils import parseaddr, parsedate_to_datetime
import re

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.auth.exceptions import RefreshError

from app.core.config import settings
from app.core.security import token_encryption
from app.models.models import User, OAuthToken, ProcessedMessage
from app.models.schemas import EmailContent
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select


class GmailError(Exception):
    """Exception for Gmail API errors."""
    pass


class GmailService:
    """Service for interacting with Gmail API."""

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
        """Get Gmail service for a user."""
        # Get user's tokens
        stmt = select(OAuthToken).where(OAuthToken.user_id == user_id)
        result = await self.db.execute(stmt)
        token_record = result.scalar_one_or_none()

        if not token_record:
            raise GmailError("No OAuth tokens found for user")

        # Decrypt tokens
        access_token = token_encryption.decrypt(token_record.access_token)
        refresh_token = token_encryption.decrypt(token_record.refresh_token)

        # Create credentials
        credentials = self._create_credentials(access_token, refresh_token)

        # Build service
        service = build('gmail', 'v1', credentials=credentials)
        return service

    async def get_profile(self, user_id: str) -> Dict[str, Any]:
        """Get Gmail profile for a user."""
        service = await self._get_service(user_id)
        try:
            profile = service.users().getProfile(userId='me').execute()
            return profile
        except HttpError as e:
            raise GmailError(f"Failed to get profile: {e}")

    async def list_messages(
        self,
        user_id: str,
        max_results: int = 50,
        query: str = None,
        label_ids: List[str] = None,
        page_token: str = None
    ) -> Tuple[List[Dict[str, str]], str]:
        """
        List Gmail messages for a user.
        Returns tuple of (messages, next_page_token).
        """
        service = await self._get_service(user_id)
        try:
            params = {
                'userId': 'me',
                'maxResults': max_results,
            }
            if query:
                params['q'] = query
            if label_ids:
                params['labelIds'] = label_ids
            if page_token:
                params['pageToken'] = page_token

            response = service.users().messages().list(**params).execute()
            messages = response.get('messages', [])
            next_page_token = response.get('nextPageToken')
            return messages, next_page_token
        except HttpError as e:
            raise GmailError(f"Failed to list messages: {e}")

    async def get_message(
        self,
        user_id: str,
        message_id: str,
        format: str = 'full'
    ) -> Dict[str, Any]:
        """Get a specific Gmail message."""
        service = await self._get_service(user_id)
        try:
            message = service.users().messages().get(
                userId='me',
                id=message_id,
                format=format
            ).execute()
            return message
        except HttpError as e:
            raise GmailError(f"Failed to get message {message_id}: {e}")

    async def get_message_headers(
        self,
        message: Dict[str, Any],
        header_names: List[str]
    ) -> Dict[str, str]:
        """Extract specific headers from a message."""
        headers = {}
        message_headers = message.get('payload', {}).get('headers', [])
        for header in message_headers:
            name = header.get('name', '').lower()
            if name in [h.lower() for h in header_names]:
                headers[name] = header.get('value', '')
        return headers

    def _decode_message_body(self, payload: Dict[str, Any]) -> str:
        """Decode message body from base64."""
        body = ""
        
        if 'body' in payload and 'data' in payload['body']:
            data = payload['body']['data']
            body = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
        
        # Handle multipart messages
        if 'parts' in payload:
            for part in payload['parts']:
                if part.get('mimeType') == 'text/plain':
                    if 'body' in part and 'data' in part['body']:
                        data = part['body']['data']
                        body = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                        break
                elif 'parts' in part:
                    # Recursive for nested parts
                    body = self._decode_message_body(part)
                    if body:
                        break
        
        return body

    def _get_html_body(self, payload: Dict[str, Any]) -> str:
        """Extract HTML body from message."""
        if 'parts' in payload:
            for part in payload['parts']:
                if part.get('mimeType') == 'text/html':
                    if 'body' in part and 'data' in part['body']:
                        data = part['body']['data']
                        return base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                elif 'parts' in part:
                    html = self._get_html_body(part)
                    if html:
                        return html
        return ""

    async def extract_email_content(
        self,
        user_id: str,
        message_id: str
    ) -> Optional[EmailContent]:
        """Extract relevant content from an email message."""
        try:
            message = await self.get_message(user_id, message_id)
            
            # Get headers
            headers = await self.get_message_headers(
                message,
                ['Subject', 'From', 'Date', 'To']
            )
            
            # Parse sender
            from_header = headers.get('from', '')
            sender_name, sender_email = parseaddr(from_header)
            
            # Parse date
            date_header = headers.get('date', '')
            try:
                date = parsedate_to_datetime(date_header) if date_header else None
            except Exception:
                date = None
            
            # Get body
            payload = message.get('payload', {})
            body_text = self._decode_message_body(payload)
            body_html = self._get_html_body(payload)
            
            # Get labels
            labels = message.get('labelIds', [])
            
            # Get thread ID
            thread_id = message.get('threadId')
            
            return EmailContent(
                message_id=message_id,
                subject=headers.get('subject', ''),
                sender=sender_name if sender_name else sender_email,
                sender_email=sender_email,
                body_text=body_text[:10000] if body_text else None,  # Limit size
                body_html=body_html[:10000] if body_html else None,
                date=date,
                labels=labels,
            )
        except GmailError as e:
            raise e
        except Exception as e:
            raise GmailError(f"Failed to extract email content: {e}")

    async def get_history(
        self,
        user_id: str,
        start_history_id: int,
        max_results: int = 100
    ) -> List[Dict[str, Any]]:
        """Get Gmail history since a specific history ID."""
        service = await self._get_service(user_id)
        try:
            response = service.users().history().list(
                userId='me',
                startHistoryId=start_history_id,
                maxResults=max_results,
                historyTypes=['messageAdded']
            ).execute()
            return response.get('history', [])
        except HttpError as e:
            raise GmailError(f"Failed to get history: {e}")

    async def setup_watch(
        self,
        user_id: str,
        topic_name: str
    ) -> Dict[str, Any]:
        """
        Set up Gmail push notifications via Pub/Sub.
        This requires the Pub/Sub topic to be configured in Google Cloud.
        """
        service = await self._get_service(user_id)
        try:
            request_body = {
                'labelIds': ['INBOX'],
                'topicName': topic_name,
            }
            response = service.users().watch(
                userId='me',
                body=request_body
            ).execute()
            return response
        except HttpError as e:
            raise GmailError(f"Failed to setup watch: {e}")

    async def stop_watch(self, user_id: str) -> bool:
        """Stop Gmail push notifications."""
        service = await self._get_service(user_id)
        try:
            service.users().stop(userId='me').execute()
            return True
        except HttpError as e:
            raise GmailError(f"Failed to stop watch: {e}")

    async def is_message_processed(
        self,
        user_id: str,
        message_id: str
    ) -> bool:
        """Check if a message has already been processed."""
        stmt = select(ProcessedMessage).where(
            ProcessedMessage.user_id == user_id,
            ProcessedMessage.gmail_message_id == message_id
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def mark_message_processed(
        self,
        user_id: str,
        message_id: str,
        thread_id: str = None,
        result: str = None,
        error_message: str = None
    ) -> ProcessedMessage:
        """Mark a message as processed."""
        processed = ProcessedMessage(
            user_id=user_id,
            gmail_message_id=message_id,
            gmail_thread_id=thread_id,
            result=result,
            error_message=error_message,
        )
        self.db.add(processed)
        await self.db.flush()
        return processed

    async def get_unprocessed_messages(
        self,
        user_id: str,
        since_days: int = 7,
        max_messages: int = 50
    ) -> List[str]:
        """Get list of unprocessed message IDs from recent history."""
        # Build query for recent messages
        since_date = (datetime.now() - timedelta(days=since_days)).strftime('%Y/%m/%d')
        query = f"after:{since_date}"
        
        messages, _ = await self.list_messages(
            user_id=user_id,
            max_results=max_messages,
            query=query
        )
        
        # Filter out already processed messages
        unprocessed = []
        for msg in messages:
            if not await self.is_message_processed(user_id, msg['id']):
                unprocessed.append(msg['id'])
        
        return unprocessed
