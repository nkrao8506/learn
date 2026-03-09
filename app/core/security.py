"""
Security utilities for token encryption and JWT handling.
"""
import base64
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from jose import JWTError, jwt
from pydantic import BaseModel

from app.core.config import settings


class TokenData(BaseModel):
    """JWT token payload data."""
    user_id: str
    email: str
    exp: datetime
    iat: datetime
    type: str = "access"


class TokenEncryption:
    """Handles encryption/decryption of OAuth tokens using Fernet symmetric encryption."""

    def __init__(self, encryption_key: str = None):
        key = encryption_key or settings.ENCRYPTION_KEY
        # Derive a valid Fernet key from the provided key
        key_bytes = key.encode('utf-8')
        salt = b'gmail_calendar_service_salt'  # Fixed salt for deterministic key derivation
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        derived_key = base64.urlsafe_b64encode(kdf.derive(key_bytes))
        self._fernet = Fernet(derived_key)

    def encrypt(self, plaintext: str) -> str:
        """Encrypt a plaintext string."""
        if not plaintext:
            return ""
        encrypted = self._fernet.encrypt(plaintext.encode('utf-8'))
        return base64.urlsafe_b64encode(encrypted).decode('utf-8')

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt a ciphertext string."""
        if not ciphertext:
            return ""
        try:
            encrypted = base64.urlsafe_b64decode(ciphertext.encode('utf-8'))
            decrypted = self._fernet.decrypt(encrypted)
            return decrypted.decode('utf-8')
        except Exception as e:
            raise ValueError(f"Failed to decrypt token: {str(e)}")


# Global encryption instance
token_encryption = TokenEncryption()


class JWTHandler:
    """Handles JWT token creation and validation."""

    @staticmethod
    def create_access_token(
        user_id: str,
        email: str,
        expires_delta: Optional[timedelta] = None
    ) -> str:
        """Create a JWT access token."""
        if expires_delta is None:
            expires_delta = timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)

        now = datetime.utcnow()
        expire = now + expires_delta

        payload = {
            "user_id": user_id,
            "email": email,
            "exp": expire,
            "iat": now,
            "type": "access"
        }

        return jwt.encode(
            payload,
            settings.JWT_SECRET_KEY,
            algorithm=settings.JWT_ALGORITHM
        )

    @staticmethod
    def create_refresh_token(
        user_id: str,
        email: str,
        expires_delta: Optional[timedelta] = None
    ) -> str:
        """Create a JWT refresh token."""
        if expires_delta is None:
            expires_delta = timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)

        now = datetime.utcnow()
        expire = now + expires_delta

        payload = {
            "user_id": user_id,
            "email": email,
            "exp": expire,
            "iat": now,
            "type": "refresh"
        }

        return jwt.encode(
            payload,
            settings.JWT_SECRET_KEY,
            algorithm=settings.JWT_ALGORITHM
        )

    @staticmethod
    def decode_token(token: str) -> Optional[TokenData]:
        """Decode and validate a JWT token."""
        try:
            payload = jwt.decode(
                token,
                settings.JWT_SECRET_KEY,
                algorithms=[settings.JWT_ALGORITHM]
            )
            return TokenData(
                user_id=payload.get("user_id"),
                email=payload.get("email"),
                exp=datetime.fromtimestamp(payload.get("exp")),
                iat=datetime.fromtimestamp(payload.get("iat")),
                type=payload.get("type", "access")
            )
        except JWTError:
            return None

    @staticmethod
    def verify_token(token: str, token_type: str = "access") -> Optional[TokenData]:
        """Verify a JWT token and check its type."""
        token_data = JWTHandler.decode_token(token)
        if token_data is None:
            return None
        if token_data.type != token_type:
            return None
        if token_data.exp < datetime.utcnow():
            return None
        return token_data


def generate_state_token() -> str:
    """Generate a secure random state token for OAuth CSRF protection."""
    return secrets.token_urlsafe(32)


def hash_state_token(state: str) -> str:
    """Hash a state token for secure storage/comparison."""
    return hashlib.sha256(state.encode('utf-8')).hexdigest()
