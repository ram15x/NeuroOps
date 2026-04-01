from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import timedelta

from backend.core.config import settings
from backend.models.database import get_db, User, AuditLog
from backend.services.auth_service import (
    authenticate_user,
    create_access_token,
    decode_token,
    get_user_by_username,
    create_default_admin
)
from backend.services.audit_logger import AuditLogger

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


@router.post("/auth/login")
def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"}
        )

    token = create_access_token(
        data={"sub": user.username, "role": user.role if hasattr(user, 'role') else "user"},
        expires_delta=timedelta(minutes=settings.JWT_EXPIRY_MINUTES)
    )

    # audit log
    AuditLogger.log(
        db,
        user_id=user.id,
        username=user.username,
        action="login",
        resource="auth",
        details={"ip": request.client.host},
        ip_address=request.client.host
    )

    return {
        "access_token": token,
        "token_type": "bearer",
        "username": user.username,
        "role": user.role if hasattr(user, 'role') else "user",
        "expires_in": f"{settings.JWT_EXPIRY_MINUTES} minutes"
    }


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    payload = decode_token(token)
    username = payload.get("sub")
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload"
        )
    
    user = get_user_by_username(db, username)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )
    
    return user


@router.get("/auth/me")
def get_me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "role": current_user.role if hasattr(current_user, 'role') else "user",
        "is_active": current_user.is_active,
        "platform": "NeuroOps",
        "status": "authenticated"
    }


@router.get("/auth/admin")
def admin_only(current_user: User = Depends(get_current_user)):
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return {
        "message": "Welcome to NeuroOps Admin Panel",
        "username": current_user.username,
        "access": "full"
    }


@router.post("/auth/init")
def init_admin(db: Session = Depends(get_db)):
    """Initialize default admin user (run once)"""
    admin = create_default_admin(db)
    return {"message": "Admin user created", "username": admin.username}