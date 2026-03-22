from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import HTTPException, status

# ── Config ─────────────────────────────────────────────
SECRET_KEY    = "neuroops-super-secret-key-2026-change-in-production"
ALGORITHM     = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

# ── Password Hashing ───────────────────────────────────
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ── Fake User DB (replace with PostgreSQL later) ───────
USERS_DB = {
    "admin": {
        "username": "admin",
        "password": pwd_context.hash("neuroops123"),
        "role"    : "admin"
    },
    "engineer": {
        "username": "engineer",
        "password": pwd_context.hash("engineer123"),
        "role"    : "engineer"
    }
}

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def authenticate_user(username: str, password: str):
    user = USERS_DB.get(username)
    if not user:
        return None
    if not verify_password(password, user["password"]):
        return None
    return user

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire    = datetime.utcnow() + (expires_delta or timedelta(minutes=60))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"}
        )
