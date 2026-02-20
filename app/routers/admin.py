"""Admin user management routes."""

from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app import templates
from models import get_db, User, VALID_ROLES, AUDIT_ACTION_CREATE, AUDIT_ACTION_UPDATE, AUDIT_ENTITY_USER
from app.services.auth_service import hash_password, require_role
from app.services.audit_service import log_audit

router = APIRouter(prefix="/admin")

_admin_dep = require_role("admin")


@router.get("/users", response_class=HTMLResponse)
async def list_users(request: Request, db: Session = Depends(get_db), current_user: User = Depends(_admin_dep)):
    users = db.query(User).order_by(User.display_name).all()
    return templates.TemplateResponse("admin_users.html", {
        "request": request,
        "users": users,
    })


@router.get("/users/new", response_class=HTMLResponse)
async def new_user_page(request: Request, current_user: User = Depends(_admin_dep)):
    return templates.TemplateResponse("admin_user_form.html", {
        "request": request,
        "edit_user": None,
        "roles": VALID_ROLES,
    })


@router.post("/users/new")
async def create_user(
    request: Request,
    email: str = Form(...),
    display_name: str = Form(...),
    password: str = Form(...),
    role: str = Form("analyst"),
    db: Session = Depends(get_db),
    current_user: User = Depends(_admin_dep),
):
    email = email.strip().lower()
    if not email or not display_name.strip() or not password:
        return templates.TemplateResponse("admin_user_form.html", {
            "request": request,
            "edit_user": None,
            "roles": VALID_ROLES,
            "error": "All fields are required.",
        })

    existing = db.query(User).filter(User.email == email).first()
    if existing:
        return templates.TemplateResponse("admin_user_form.html", {
            "request": request,
            "edit_user": None,
            "roles": VALID_ROLES,
            "error": f"A user with email '{email}' already exists.",
        })

    if role not in VALID_ROLES:
        role = "analyst"

    user = User(
        email=email,
        display_name=display_name.strip(),
        password_hash=hash_password(password),
        role=role,
        is_active=True,
    )
    db.add(user)
    db.flush()
    log_audit(db, AUDIT_ACTION_CREATE, AUDIT_ENTITY_USER,
              entity_id=user.id, entity_label=f"{user.display_name} ({user.email})",
              new_value={"email": user.email, "display_name": user.display_name, "role": user.role},
              description=f"User created: {user.display_name} ({user.email}), role={user.role}",
              actor_user=current_user,
              ip_address=request.client.host if request.client else None)
    db.commit()

    return RedirectResponse(
        url="/admin/users?message=User created successfully&message_type=success",
        status_code=303,
    )


@router.get("/users/{user_id}/edit", response_class=HTMLResponse)
async def edit_user_page(request: Request, user_id: int, db: Session = Depends(get_db), current_user: User = Depends(_admin_dep)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return templates.TemplateResponse("admin_user_form.html", {
        "request": request,
        "edit_user": user,
        "roles": VALID_ROLES,
    })


@router.post("/users/{user_id}/edit")
async def update_user(
    request: Request,
    user_id: int,
    display_name: str = Form(...),
    role: str = Form("analyst"),
    is_active: str = Form(""),
    new_password: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(_admin_dep),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not display_name.strip():
        return templates.TemplateResponse("admin_user_form.html", {
            "request": request,
            "edit_user": user,
            "roles": VALID_ROLES,
            "error": "Display name is required.",
        })

    # Prevent admin from deactivating themselves
    if user.id == current_user.id and is_active != "on":
        return templates.TemplateResponse("admin_user_form.html", {
            "request": request,
            "edit_user": user,
            "roles": VALID_ROLES,
            "error": "You cannot deactivate your own account.",
        })

    # Prevent admin from demoting themselves
    if user.id == current_user.id and role != "admin":
        return templates.TemplateResponse("admin_user_form.html", {
            "request": request,
            "edit_user": user,
            "roles": VALID_ROLES,
            "error": "You cannot change your own role from admin.",
        })

    old_vals = {"display_name": user.display_name, "role": user.role, "is_active": user.is_active}
    user.display_name = display_name.strip()
    if role in VALID_ROLES:
        user.role = role
    user.is_active = is_active == "on"

    if new_password.strip():
        user.password_hash = hash_password(new_password.strip())

    log_audit(db, AUDIT_ACTION_UPDATE, AUDIT_ENTITY_USER,
              entity_id=user.id, entity_label=f"{user.display_name} ({user.email})",
              old_value=old_vals,
              new_value={"display_name": user.display_name, "role": user.role, "is_active": user.is_active},
              description=f"User updated: {user.display_name}",
              actor_user=current_user,
              ip_address=request.client.host if request.client else None)
    db.commit()

    return RedirectResponse(
        url=f"/admin/users?message=User '{user.display_name}' updated&message_type=success",
        status_code=303,
    )
