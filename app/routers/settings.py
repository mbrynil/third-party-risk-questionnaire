from datetime import datetime

from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app import templates
from models import (
    get_db, ReminderConfig, ReminderLog, User,
    ensure_reminder_config, ScoringConfig, ensure_scoring_config,
    TieringRule,
    VALID_DATA_CLASSIFICATIONS, VALID_BUSINESS_CRITICALITIES,
    VALID_ACCESS_LEVELS, VALID_INHERENT_RISK_TIERS,
)
from app.services.reminder_service import get_reminder_stats
from app.services.scheduler import run_now
from app.services.auth_service import require_role

router = APIRouter()

_admin_dep = require_role("admin")


@router.get("/settings/reminders", response_class=HTMLResponse)
async def reminder_settings_page(request: Request, db: Session = Depends(get_db), current_user: User = Depends(_admin_dep)):
    config = ensure_reminder_config(db)
    stats = get_reminder_stats(db)

    recent_logs = db.query(ReminderLog).order_by(
        ReminderLog.sent_at.desc()
    ).limit(20).all()

    return templates.TemplateResponse("reminder_settings.html", {
        "request": request,
        "config": config,
        "stats": stats,
        "recent_logs": recent_logs,
    })


@router.post("/settings/reminders")
async def update_reminder_settings(
    request: Request,
    enabled: str = Form("off"),
    first_reminder_days: int = Form(3),
    frequency_days: int = Form(7),
    max_reminders: int = Form(3),
    escalation_after: int = Form(2),
    escalation_email: str = Form(""),
    final_notice_days_before_expiry: int = Form(3),
    db: Session = Depends(get_db),
    current_user: User = Depends(_admin_dep),
):
    config = ensure_reminder_config(db)
    config.enabled = (enabled == "on")
    config.first_reminder_days = max(1, first_reminder_days)
    config.frequency_days = max(1, frequency_days)
    config.max_reminders = max(1, max_reminders)
    config.escalation_after = max(1, min(escalation_after, config.max_reminders))
    config.escalation_email = escalation_email.strip() or None
    config.final_notice_days_before_expiry = max(0, final_notice_days_before_expiry)
    config.updated_at = datetime.utcnow()
    db.commit()

    return RedirectResponse(url="/settings/reminders?saved=1", status_code=303)


@router.post("/settings/reminders/run-now")
async def trigger_reminders_now(request: Request, current_user: User = Depends(_admin_dep)):
    """Manually trigger a reminder check cycle."""
    summary = run_now()
    sent = summary.get("reminders_sent", 0)
    escalated = summary.get("escalations_sent", 0)
    return RedirectResponse(
        url=f"/settings/reminders?ran=1&sent={sent}&escalated={escalated}",
        status_code=303,
    )


# ==================== SCORING CONFIG ====================

@router.get("/settings/scoring", response_class=HTMLResponse)
async def scoring_settings_page(request: Request, db: Session = Depends(get_db), current_user: User = Depends(_admin_dep)):
    config = ensure_scoring_config(db)
    return templates.TemplateResponse("scoring_settings.html", {
        "request": request,
        "config": config,
    })


@router.post("/settings/scoring")
async def update_scoring_settings(
    request: Request,
    very_low_min: int = Form(90),
    low_min: int = Form(70),
    moderate_min: int = Form(50),
    high_min: int = Form(30),
    db: Session = Depends(get_db),
    current_user: User = Depends(_admin_dep),
):
    config = ensure_scoring_config(db)
    config.very_low_min = max(0, min(100, very_low_min))
    config.low_min = max(0, min(config.very_low_min - 1, low_min))
    config.moderate_min = max(0, min(config.low_min - 1, moderate_min))
    config.high_min = max(0, min(config.moderate_min - 1, high_min))
    config.updated_at = datetime.utcnow()
    db.commit()
    return RedirectResponse(url="/settings/scoring?saved=1", status_code=303)


# ==================== TIERING RULES ====================

TIERING_FIELDS = {
    "data_classification": VALID_DATA_CLASSIFICATIONS,
    "business_criticality": VALID_BUSINESS_CRITICALITIES,
    "access_level": VALID_ACCESS_LEVELS,
}


@router.get("/settings/tiering", response_class=HTMLResponse)
async def tiering_settings_page(request: Request, db: Session = Depends(get_db), current_user: User = Depends(_admin_dep)):
    rules = db.query(TieringRule).order_by(TieringRule.priority).all()
    return templates.TemplateResponse("tiering_settings.html", {
        "request": request,
        "rules": rules,
        "fields": TIERING_FIELDS,
        "tiers": VALID_INHERENT_RISK_TIERS,
    })


@router.post("/settings/tiering/add")
async def add_tiering_rule(
    request: Request,
    field: str = Form(...),
    value: str = Form(...),
    tier: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(_admin_dep),
):
    max_priority = db.query(TieringRule).count()
    db.add(TieringRule(field=field, value=value, tier=tier, priority=max_priority))
    db.commit()
    return RedirectResponse(url="/settings/tiering?saved=1", status_code=303)


@router.post("/settings/tiering/{rule_id}/delete")
async def delete_tiering_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_admin_dep),
):
    rule = db.query(TieringRule).filter(TieringRule.id == rule_id).first()
    if rule:
        db.delete(rule)
        db.commit()
    return RedirectResponse(url="/settings/tiering?saved=1", status_code=303)
