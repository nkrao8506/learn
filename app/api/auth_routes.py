"""
Authentication API routes.
"""
from datetime import timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import (
    JWTHandler,
    generate_state_token,
    hash_state_token,
    get_client_ip,
)
from app.auth.oauth import AuthService, google_oauth
from app.auth.dependencies import get_current_user, get_current_user_optional
from app.models.models import User, AuditLog
from app.models.schemas import (
    AuthResponse,
    UserResponse,
    TokenResponse,
    TokenRefresh,
    ErrorResponse,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])

# In-memory store for state tokens (in production, use Redis)
state_tokens = {}


@router.get("/google")
async def google_auth(request: Request):
    """
    Initiate Google OAuth flow.
    Redirects user to Google consent screen.
    """
    # Generate state token for CSRF protection
    state = generate_state_token()
    state_hash = hash_state_token(state)
    
    # Store state with timestamp for validation
    state_tokens[state_hash] = {
        "created_at": request.state.start_time if hasattr(request.state, 'start_time') else None,
        "ip": get_client_ip(request),
    }
    
    # Generate authorization URL
    auth_url = google_oauth.get_authorization_url(state)
    
    # Set state in cookie for additional validation
    response = RedirectResponse(url=auth_url)
    response.set_cookie(
        key="oauth_state",
        value=state,
        httponly=True,
        max_age=600,  # 10 minutes
        secure=not settings.DEBUG,
        samesite="lax",
    )
    
    return response


@router.get("/callback", response_model=AuthResponse)
async def google_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    request: Request = None,
):
    """
    Handle OAuth callback from Google.
    Exchanges authorization code for tokens and creates session.
    """
    # Check for OAuth errors
    if error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"OAuth error: {error}"
        )
    
    if not code or not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing code or state parameter"
        )
    
    # Validate state token (CSRF protection)
    state_hash = hash_state_token(state)
    if state_hash not in state_tokens:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid state token"
        )
    
    # Remove used state
    del state_tokens[state_hash]
    
    # Handle OAuth callback
    try:
        auth_service = AuthService(db)
        user, tokens = await auth_service.handle_oauth_callback(code)
        
        # Create JWT tokens
        access_token = JWTHandler.create_access_token(
            user_id=str(user.id),
            email=user.email
        )
        refresh_token = JWTHandler.create_refresh_token(
            user_id=str(user.id),
            email=user.email
        )
        
        # Log the login
        audit_log = AuditLog(
            user_id=user.id,
            action="login",
            resource_type="user",
            resource_id=user.id,
            ip_address=get_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
        db.add(audit_log)
        await db.commit()
        
        return AuthResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            user=UserResponse.model_validate(user),
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Authentication failed: {str(e)}"
        )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    token_data: TokenRefresh,
    db: AsyncSession = Depends(get_db),
):
    """
    Refresh an access token using a refresh token.
    """
    # Verify refresh token
    token_payload = JWTHandler.verify_token(token_data.refresh_token, token_type="refresh")
    
    if not token_payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token"
        )
    
    # Create new access token
    access_token = JWTHandler.create_access_token(
        user_id=token_payload.user_id,
        email=token_payload.email
    )
    
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/logout")
async def logout(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
):
    """
    Logout the current user.
    Revokes Google OAuth tokens and invalidates session.
    """
    auth_service = AuthService(db)
    await auth_service.logout(str(user.id))
    
    # Log the logout
    audit_log = AuditLog(
        user_id=user.id,
        action="logout",
        resource_type="user",
        resource_id=user.id,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent") if request else None,
    )
    db.add(audit_log)
    await db.commit()
    
    return {"message": "Logged out successfully"}


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    user: User = Depends(get_current_user),
):
    """
    Get current authenticated user information.
    """
    return UserResponse.model_validate(user)


@router.get("/status")
async def auth_status(
    user: Optional[User] = Depends(get_current_user_optional),
):
    """
    Check authentication status.
    Returns whether the user is authenticated.
    """
    if user:
        return {
            "authenticated": True,
            "email": user.email,
            "name": user.name,
        }
    return {"authenticated": False}
