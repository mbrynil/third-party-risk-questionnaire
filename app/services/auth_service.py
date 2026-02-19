"""Authentication service: password hashing, session cookies, login helpers."""

import os
from datetime import datetime

import bcrypt
from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from sqlalchemy.orm import Session

from models import get_db, User

SECRET_KEY = os.environ.get("SESSION_SECRET", "dev-secret-change-in-production")
SESSION_COOKIE = "session"
SESSION_MAX_AGE = 86400  # 24 hours

_serializer = URLSafeTimedSerializer(SECRET_KEY)


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_session_cookie(user_id: int) -> str:
    return _serializer.dumps({"uid": user_id})


def validate_session_cookie(token: str) -> int | None:
    try:
        data = _serializer.loads(token, max_age=SESSION_MAX_AGE)
        return data.get("uid")
    except (BadSignature, SignatureExpired):
        return None


def get_current_user(request: Request, db: Session) -> User | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    user_id = validate_session_cookie(token)
    if user_id is None:
        return None
    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    return user


class _LoginRequired(Exception):
    """Raised internally to signal auth redirect."""
    pass


def require_login(request: Request, db: Session = Depends(get_db)) -> User:
    user = get_current_user(request, db)
    if user is None:
        # For JSON API requests, return 401
        accept = request.headers.get("accept", "")
        if "application/json" in accept:
            raise HTTPException(status_code=401, detail="Not authenticated")
        # For HTML, raise redirect via HTTPException with 303
        raise HTTPException(status_code=303, detail="Not authenticated",
                            headers={"Location": "/login"})
    return user


def require_role(*roles: str):
    """Return a Depends-compatible callable that checks role membership."""
    def _checker(request: Request, db: Session = Depends(get_db)) -> User:
        user = get_current_user(request, db)
        if user is None:
            accept = request.headers.get("accept", "")
            if "application/json" in accept:
                raise HTTPException(status_code=401, detail="Not authenticated")
            raise HTTPException(status_code=303, detail="Not authenticated",
                                headers={"Location": "/login"})
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="You do not have permission to access this page.")
        return user
    return _checker
