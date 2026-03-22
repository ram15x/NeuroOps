from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from backend.services.auth_service import (
    authenticate_user,
    create_access_token,
    decode_token
)
from datetime import timedelta

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

#login
@router.post("/auth/login")
def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"}
        )

    token = create_access_token(
        data={"sub": user["username"], "role": user["role"]},
        expires_delta=timedelta(minutes=60)
    )

    return {
        "access_token": token,
        "token_type"  : "bearer",
        "username"    : user["username"],
        "role"        : user["role"],
        "expires_in"  : "60 minutes"
    }

#Get Current User
def get_current_user(token: str = Depends(oauth2_scheme)):
    payload = decode_token(token)
    username = payload.get("sub")
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload"
        )
    return {"username": username, "role": payload.get("role")}

#protected: Me
@router.get("/auth/me")
def get_me(current_user: dict = Depends(get_current_user)):
    return {
        "username": current_user["username"],
        "role"    : current_user["role"],
        "platform": "NeuroOps",
        "status"  : "authenticated"
    }

#protected: admin only
@router.get("/auth/admin")
def admin_only(current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return {
        "message" : "Welcome to NeuroOps Admin Panel",
        "username": current_user["username"],
        "access"  : "full"
    }