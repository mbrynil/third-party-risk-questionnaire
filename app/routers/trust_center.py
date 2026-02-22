"""Trust Center routes — public trust center page + admin settings."""

from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app import templates
from models import (
    get_db, User, TrustCenterConfig,
    AUDIT_ACTION_UPDATE, AUDIT_ENTITY_SLA_CONFIG,
)
from app.services.auth_service import require_role
from app.services.audit_service import log_audit
from app.services import trust_center_service as svc

router = APIRouter()

_admin_dep = require_role("admin")


# ==================== PUBLIC PAGE (NO AUTH) ====================

@router.get("/trust-center/{token}", response_class=HTMLResponse)
async def trust_center_public(request: Request, token: str, db: Session = Depends(get_db)):
    """Public-facing trust center page. Validates token, no login required."""
    config = svc.get_config(db)
    if not config or not config.is_enabled or config.access_token != token:
        raise HTTPException(status_code=404, detail="Not found")

    data = svc.get_public_data(db)
    return templates.TemplateResponse("trust_center_public.html", {
        "request": request,
        "config": config,
        "data": data,
    })


# ==================== ADMIN SETTINGS ====================

@router.get("/settings/trust-center", response_class=HTMLResponse)
async def trust_center_settings(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(_admin_dep),
):
    config = svc.get_config(db)
    return templates.TemplateResponse("trust_center_settings.html", {
        "request": request,
        "config": config,
    })


@router.post("/settings/trust-center", response_class=HTMLResponse)
async def trust_center_settings_save(
    request: Request,
    is_enabled: str = Form("off"),
    company_name: str = Form("Our Organization"),
    company_description: str = Form(""),
    primary_color: str = Form("#2563eb"),
    contact_email: str = Form(""),
    show_frameworks: str = Form("off"),
    show_controls_summary: str = Form("off"),
    show_policies: str = Form("off"),
    show_certifications: str = Form("off"),
    custom_message: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(_admin_dep),
):
    old_config = svc.get_config(db)
    old_vals = {
        "is_enabled": old_config.is_enabled,
        "company_name": old_config.company_name,
        "show_frameworks": old_config.show_frameworks,
        "show_controls_summary": old_config.show_controls_summary,
        "show_policies": old_config.show_policies,
        "show_certifications": old_config.show_certifications,
    }

    svc.update_config(
        db,
        is_enabled=(is_enabled == "on"),
        company_name=company_name.strip() or "Our Organization",
        company_description=company_description.strip() or None,
        primary_color=primary_color.strip() or "#2563eb",
        contact_email=contact_email.strip() or None,
        show_frameworks=(show_frameworks == "on"),
        show_controls_summary=(show_controls_summary == "on"),
        show_policies=(show_policies == "on"),
        show_certifications=(show_certifications == "on"),
        custom_message=custom_message.strip() or None,
    )

    log_audit(
        db,
        action=AUDIT_ACTION_UPDATE,
        entity_type=AUDIT_ENTITY_SLA_CONFIG,
        entity_id=old_config.id,
        entity_label="Trust Center Config",
        old_value=old_vals,
        new_value={
            "is_enabled": is_enabled == "on",
            "company_name": company_name.strip(),
        },
        description="Trust Center configuration updated",
        actor_user=current_user,
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return RedirectResponse(url="/settings/trust-center?saved=1", status_code=303)


@router.post("/settings/trust-center/regenerate-token", response_class=HTMLResponse)
async def trust_center_regenerate_token(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(_admin_dep),
):
    config = svc.regenerate_token(db)
    log_audit(
        db,
        action=AUDIT_ACTION_UPDATE,
        entity_type=AUDIT_ENTITY_SLA_CONFIG,
        entity_id=config.id,
        entity_label="Trust Center Config",
        description="Trust Center access token regenerated",
        actor_user=current_user,
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return RedirectResponse(url="/settings/trust-center?regenerated=1", status_code=303)
