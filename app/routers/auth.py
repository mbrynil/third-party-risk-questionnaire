"""Authentication routes: login, logout, account management."""

from datetime import datetime

from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from models import get_db, User
from app.services.auth_service import (
    verify_password, hash_password, create_session_cookie,
    get_current_user, require_login, SESSION_COOKIE,
)

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@router.post("/login")
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.email == email).first()
    if not user or not user.is_active or not verify_password(password, user.password_hash):
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Invalid email or password.",
        })

    user.last_login_at = datetime.utcnow()
    db.commit()

    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        create_session_cookie(user.id),
        httponly=True,
        samesite="lax",
        max_age=86400,
    )
    return response


@router.get("/logout")
def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response


@router.get("/account")
def account_page(
    request: Request,
    current_user: User = Depends(require_login),
):
    return templates.TemplateResponse("account.html", {
        "request": request,
        "current_user": current_user,
        "message": None,
    })


@router.post("/account")
def update_account(
    request: Request,
    display_name: str = Form(...),
    current_password: str = Form(""),
    new_password: str = Form(""),
    confirm_password: str = Form(""),
    current_user: User = Depends(require_login),
    db: Session = Depends(get_db),
):
    current_user.display_name = display_name.strip()

    error = None
    success = None

    if new_password:
        if not current_password:
            error = "Current password is required to change your password."
        elif not verify_password(current_password, current_user.password_hash):
            error = "Current password is incorrect."
        elif len(new_password) < 8:
            error = "New password must be at least 8 characters."
        elif new_password != confirm_password:
            error = "New passwords do not match."
        else:
            current_user.password_hash = hash_password(new_password)
            success = "Password updated successfully."

    if not error:
        db.commit()
        if not success:
            success = "Account updated."

    return templates.TemplateResponse("account.html", {
        "request": request,
        "current_user": current_user,
        "message": error or success,
        "message_type": "danger" if error else "success",
    })
