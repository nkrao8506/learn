"""
Google OAuth2 authentication service.
"""
import httpx
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from urllib.parse import urlencode
import json

from app.core.config import settings
from app.core.security import token_encryption, generate_state_token, hash_state_token
from app.models.models import User, OAuthToken, UserSettings
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select


class GoogleOAuthError(Exception):
    """Exception for Google OAuth errors."""
    pass


class GoogleOAuthService:
    """Service for handling Google OAuth2 authentication."""

    AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

    def __init__(self):
        self.client_id = settings.GOOGLE_CLIENT_ID
        self.client_secret = settings.GOOGLE_CLIENT_SECRET
        self.redirect_uri = settings.GOOGLE_REDIRECT_URI
        self.scopes = settings.GOOGLE_SCOPES

    def get_authorization_url(self, state: str) -> str:
        """Generate the Google OAuth authorization URL."""
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.scopes),
            "access_type": "offline",  # Required for refresh token
            "prompt": "consent",  # Force consent screen to get refresh token
            "state": state,
        }
        return f"{self.AUTHORIZE_URL}?{urlencode(params)}"

    async def exchange_code_for_tokens(self, code: str) -> Dict[str, Any]:
        """Exchange authorization code for access and refresh tokens."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.TOKEN_URL,
                data={
                    "code": code,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "redirect_uri": self.redirect_uri,
                    "grant_type": "authorization_code",
                },
                timeout=30.0,
            )

        if response.status_code != 200:
            raise GoogleOAuthError(f"Failed to exchange code: {response.text}")

        return response.json()

    async def refresh_access_token(self, refresh_token: str) -> Dict[str, Any]:
        """Refresh an access token using a refresh token."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.TOKEN_URL,
                data={
                    "refresh_token": refresh_token,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "grant_type": "refresh_token",
                },
                timeout=30.0,
            )

        if response.status_code != 200:
            raise GoogleOAuthError(f"Failed to refresh token: {response.text}")

        return response.json()

    async def get_user_info(self, access_token: str) -> Dict[str, Any]:
        """Get user information from Google using access token."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                self.USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=30.0,
            )

        if response.status_code != 200:
            raise GoogleOAuthError(f"Failed to get user info: {response.text}")

        return response.json()

    async def revoke_token(self, token: str) -> bool:
        """Revoke a Google OAuth token."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://oauth2.googleapis.com/revoke",
                params={"token": token},
                timeout=30.0,
            )
        return response.status_code == 200


class AuthService:
    """Service for handling authentication operations."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.oauth = GoogleOAuthService()

    async def get_or_create_user(
        self,
        google_id: str,
        email: str,
        name: Optional[str] = None,
        picture_url: Optional[str] = None
    ) -> User:
        """Get existing user or create a new one."""
        # Check if user exists
        stmt = select(User).where(User.google_id == google_id)
        result = await self.db.execute(stmt)
        user = result.scalar_one_or_none()

        if user:
            # Update user info if changed
            if name and user.name != name:
                user.name = name
            if picture_url and user.picture_url != picture_url:
                user.picture_url = picture_url
            user.updated_at = datetime.utcnow()
            await self.db.flush()
            return user

        # Create new user
        user = User(
            google_id=google_id,
            email=email,
            name=name,
            picture_url=picture_url,
        )
        self.db.add(user)
        await self.db.flush()

        # Create default settings for user
        settings_obj = UserSettings(user_id=user.id)
        self.db.add(settings_obj)
        await self.db.flush()

        return user

    async def store_tokens(
        self,
        user_id: str,
        access_token: str,
        refresh_token: str,
        expires_in: int,
        scope: str
    ) -> OAuthToken:
        """Store OAuth tokens for a user (encrypted)."""
        # Encrypt tokens before storage
        encrypted_access = token_encryption.encrypt(access_token)
        encrypted_refresh = token_encryption.encrypt(refresh_token)

        # Check if token record exists
        stmt = select(OAuthToken).where(OAuthToken.user_id == user_id)
        result = await self.db.execute(stmt)
        token_record = result.scalar_one_or_none()

        expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

        if token_record:
            # Update existing token
            token_record.access_token = encrypted_access
            token_record.refresh_token = encrypted_refresh
            token_record.expires_at = expires_at
            token_record.scope = scope
            token_record.updated_at = datetime.utcnow()
        else:
            # Create new token record
            token_record = OAuthToken(
                user_id=user_id,
                access_token=encrypted_access,
                refresh_token=encrypted_refresh,
                expires_at=expires_at,
                scope=scope,
            )
            self.db.add(token_record)

        await self.db.flush()
        return token_record

    async def get_valid_access_token(self, user_id: str) -> Optional[str]:
        """Get a valid access token for a user, refreshing if necessary."""
        stmt = select(OAuthToken).where(OAuthToken.user_id == user_id)
        result = await self.db.execute(stmt)
        token_record = result.scalar_one_or_none()

        if not token_record:
            return None

        # Decrypt refresh token
        refresh_token = token_encryption.decrypt(token_record.refresh_token)

        # Check if access token is still valid (with 5 minute buffer)
        if token_record.expires_at and token_record.expires_at > datetime.utcnow() + timedelta(minutes=5):
            return token_encryption.decrypt(token_record.access_token)

        # Token expired, refresh it
        try:
            new_tokens = await self.oauth.refresh_access_token(refresh_token)
            
            # Update stored tokens
            encrypted_access = token_encryption.encrypt(new_tokens["access_token"])
            expires_in = new_tokens.get("expires_in", 3600)
            expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

            token_record.access_token = encrypted_access
            token_record.expires_at = expires_at
            token_record.updated_at = datetime.utcnow()

            # If a new refresh token is provided, update it too
            if "refresh_token" in new_tokens:
                token_record.refresh_token = token_encryption.encrypt(new_tokens["refresh_token"])

            await self.db.flush()

            return new_tokens["access_token"]
        except Exception as e:
            # Token refresh failed, user needs to re-authenticate
            return None

    async def logout(self, user_id: str) -> bool:
        """Logout a user by revoking their tokens."""
        stmt = select(OAuthToken).where(OAuthToken.user_id == user_id)
        result = await self.db.execute(stmt)
        token_record = result.scalar_one_or_none()

        if token_record:
            # Try to revoke the token with Google
            try:
                access_token = token_encryption.decrypt(token_record.access_token)
                await self.oauth.revoke_token(access_token)
            except Exception:
                pass  # Ignore revocation errors

            # Delete the token record
            await self.db.delete(token_record)
            await self.db.flush()

        return True

    async def handle_oauth_callback(self, code: str) -> tuple[User, Dict[str, Any]]:
        """Handle OAuth callback and return user with token info."""
        # Exchange code for tokens
        tokens = await self.oauth.exchange_code_for_tokens(code)

        # Get user info
        user_info = await self.oauth.get_user_info(tokens["access_token"])

        # Create or get user
        user = await self.get_or_create_user(
            google_id=user_info["id"],
            email=user_info["email"],
            name=user_info.get("name"),
            picture_url=user_info.get("picture"),
        )

        # Store tokens
        await self.store_tokens(
            user_id=str(user.id),
            access_token=tokens["access_token"],
            refresh_token=tokens["refresh_token"],
            expires_in=tokens.get("expires_in", 3600),
            scope=tokens.get("scope", ""),
        )

        return user, tokens


# Singleton OAuth service
google_oauth = GoogleOAuthService()
