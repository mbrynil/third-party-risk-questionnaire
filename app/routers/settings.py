from datetime import datetime

from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app import templates
from models import (
    get_db, ReminderConfig, ReminderLog, User,
    ensure_reminder_config, ScoringConfig, ensure_scoring_config,
    TieringRule, SLAConfig, ensure_sla_configs,
    VALID_DATA_CLASSIFICATIONS, VALID_BUSINESS_CRITICALITIES,
    VALID_ACCESS_LEVELS, VALID_INHERENT_RISK_TIERS,
    AUDIT_ACTION_UPDATE, AUDIT_ACTION_CREATE, AUDIT_ACTION_DELETE,
    AUDIT_ENTITY_SCORING_CONFIG, AUDIT_ENTITY_TIERING_RULE,
    AUDIT_ENTITY_REMINDER_CONFIG, AUDIT_ENTITY_SLA_CONFIG,
)
from app.services.reminder_service import get_reminder_stats
from app.services.scheduler import run_now, run_sla_now
from app.services.audit_service import log_audit
from app.services.auth_service import require_login, require_role

router = APIRouter()

_admin_dep = require_role("admin")


@router.get("/settings", response_class=HTMLResponse)
async def settings_hub(request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_login)):
    from models import TieringRule, ScoringConfig
    tiering_count = db.query(TieringRule).count()
    return templates.TemplateResponse("settings_hub.html", {
        "request": request,
        "tiering_count": tiering_count,
    })


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
    old_vals = {"enabled": config.enabled, "first_reminder_days": config.first_reminder_days,
                "frequency_days": config.frequency_days, "max_reminders": config.max_reminders}
    config.enabled = (enabled == "on")
    config.first_reminder_days = max(1, first_reminder_days)
    config.frequency_days = max(1, frequency_days)
    config.max_reminders = max(1, max_reminders)
    config.escalation_after = max(1, min(escalation_after, config.max_reminders))
    config.escalation_email = escalation_email.strip() or None
    config.final_notice_days_before_expiry = max(0, final_notice_days_before_expiry)
    config.updated_at = datetime.utcnow()
    log_audit(db, AUDIT_ACTION_UPDATE, AUDIT_ENTITY_REMINDER_CONFIG,
              entity_id=config.id, entity_label="Reminder Config",
              old_value=old_vals,
              new_value={"enabled": config.enabled, "first_reminder_days": config.first_reminder_days,
                         "frequency_days": config.frequency_days, "max_reminders": config.max_reminders},
              description="Reminder configuration updated",
              actor_user=current_user,
              ip_address=request.client.host if request.client else None)
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
    old_vals = {"very_low_min": config.very_low_min, "low_min": config.low_min,
                "moderate_min": config.moderate_min, "high_min": config.high_min}
    config.very_low_min = max(0, min(100, very_low_min))
    config.low_min = max(0, min(config.very_low_min - 1, low_min))
    config.moderate_min = max(0, min(config.low_min - 1, moderate_min))
    config.high_min = max(0, min(config.moderate_min - 1, high_min))
    config.updated_at = datetime.utcnow()
    log_audit(db, AUDIT_ACTION_UPDATE, AUDIT_ENTITY_SCORING_CONFIG,
              entity_id=config.id, entity_label="Scoring Config",
              old_value=old_vals,
              new_value={"very_low_min": config.very_low_min, "low_min": config.low_min,
                         "moderate_min": config.moderate_min, "high_min": config.high_min},
              description="Scoring thresholds updated",
              actor_user=current_user,
              ip_address=request.client.host if request.client else None)
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
    rule = TieringRule(field=field, value=value, tier=tier, priority=max_priority)
    db.add(rule)
    db.flush()
    log_audit(db, AUDIT_ACTION_CREATE, AUDIT_ENTITY_TIERING_RULE,
              entity_id=rule.id,
              entity_label=f"{field}={value} → {tier}",
              new_value={"field": field, "value": value, "tier": tier},
              description=f"Tiering rule created: {field}={value} → {tier}",
              actor_user=current_user,
              ip_address=request.client.host if request.client else None)
    db.commit()
    return RedirectResponse(url="/settings/tiering?saved=1", status_code=303)


@router.post("/settings/tiering/{rule_id}/delete")
async def delete_tiering_rule(
    rule_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(_admin_dep),
):
    rule = db.query(TieringRule).filter(TieringRule.id == rule_id).first()
    if rule:
        log_audit(db, AUDIT_ACTION_DELETE, AUDIT_ENTITY_TIERING_RULE,
                  entity_id=rule.id,
                  entity_label=f"{rule.field}={rule.value} → {rule.tier}",
                  old_value={"field": rule.field, "value": rule.value, "tier": rule.tier},
                  description=f"Tiering rule deleted: {rule.field}={rule.value} → {rule.tier}",
                  actor_user=current_user,
                  ip_address=request.client.host if request.client else None)
        db.delete(rule)
        db.commit()
    return RedirectResponse(url="/settings/tiering?saved=1", status_code=303)


# ==================== SLA CONFIG ====================

@router.get("/settings/sla", response_class=HTMLResponse)
async def sla_settings_page(request: Request, db: Session = Depends(get_db), current_user: User = Depends(_admin_dep)):
    configs = ensure_sla_configs(db)
    reminder_cfg = ensure_reminder_config(db)
    sla_enabled = getattr(reminder_cfg, "sla_enabled", True)
    return templates.TemplateResponse("sla_settings.html", {
        "request": request,
        "configs": configs,
        "sla_enabled": sla_enabled,
    })


@router.post("/settings/sla")
async def update_sla_settings(
    request: Request,
    sla_enabled: str = Form("off"),
    db: Session = Depends(get_db),
    current_user: User = Depends(_admin_dep),
):
    form = await request.form()

    # Global toggle
    reminder_cfg = ensure_reminder_config(db)
    old_enabled = getattr(reminder_cfg, "sla_enabled", True)
    new_enabled = sla_enabled == "on"
    reminder_cfg.sla_enabled = new_enabled

    # Per-tier configs
    configs = db.query(SLAConfig).all()
    for cfg in configs:
        prefix = f"tier_{cfg.id}_"
        resp_days = form.get(f"{prefix}response_deadline_days")
        rev_days = form.get(f"{prefix}review_deadline_days")
        warn_pct = form.get(f"{prefix}warning_threshold_pct")
        enabled = form.get(f"{prefix}enabled")

        old_vals = {
            "response_deadline_days": cfg.response_deadline_days,
            "review_deadline_days": cfg.review_deadline_days,
            "warning_threshold_pct": cfg.warning_threshold_pct,
            "enabled": cfg.enabled,
        }

        if resp_days is not None:
            cfg.response_deadline_days = max(1, int(resp_days))
        if rev_days is not None:
            cfg.review_deadline_days = max(1, int(rev_days))
        if warn_pct is not None:
            cfg.warning_threshold_pct = max(1, min(100, int(warn_pct)))
        cfg.enabled = enabled == "on"
        cfg.updated_at = datetime.utcnow()

        new_vals = {
            "response_deadline_days": cfg.response_deadline_days,
            "review_deadline_days": cfg.review_deadline_days,
            "warning_threshold_pct": cfg.warning_threshold_pct,
            "enabled": cfg.enabled,
        }

        if old_vals != new_vals:
            log_audit(db, AUDIT_ACTION_UPDATE, AUDIT_ENTITY_SLA_CONFIG,
                      entity_id=cfg.id,
                      entity_label=f"SLA Config: {cfg.tier}",
                      old_value=old_vals,
                      new_value=new_vals,
                      description=f"SLA config updated for {cfg.tier}",
                      actor_user=current_user,
                      ip_address=request.client.host if request.client else None)

    db.commit()
    return RedirectResponse(url="/settings/sla?saved=1", status_code=303)


@router.post("/settings/sla/run-now")
async def trigger_sla_check_now(request: Request, current_user: User = Depends(_admin_dep)):
    """Manually trigger an SLA breach check."""
    summary = run_sla_now()
    breaches = summary.get("new_breaches", 0)
    warnings = summary.get("new_warnings", 0)
    return RedirectResponse(
        url=f"/settings/sla?ran=1&breaches={breaches}&warnings={warnings}",
        status_code=303,
    )
