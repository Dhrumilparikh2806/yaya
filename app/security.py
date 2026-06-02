"""
Password hashing and JWT token utilities.

hash_password   — bcrypt hash (cost factor from bcrypt default, currently 12).
verify_password — constant-time bcrypt comparison.
create_access_token — signs an HS256 JWT containing {sub, role, exp}.
decode_token    — verifies signature and expiry; raises HTTP 401 on any failure.
"""

from datetime import datetime, timedelta

import bcrypt
from jose import JWTError, jwt
from fastapi import HTTPException, status


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(data: dict, expires_minutes: int) -> str:
    from app.config import settings
    to_encode = data.copy()
    to_encode["exp"] = datetime.utcnow() + timedelta(minutes=expires_minutes)
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> dict:
    from app.config import settings
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
