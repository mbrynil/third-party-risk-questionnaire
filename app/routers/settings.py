from datetime import datetime

from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app import templates
from models import get_db, ReminderConfig, ReminderLog, ensure_reminder_config
from app.services.reminder_service import get_reminder_stats
from app.services.scheduler import run_now

router = APIRouter()


@router.get("/settings/reminders", response_class=HTMLResponse)
async def reminder_settings_page(request: Request, db: Session = Depends(get_db)):
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
async def trigger_reminders_now(request: Request):
    """Manually trigger a reminder check cycle."""
    summary = run_now()
    sent = summary.get("reminders_sent", 0)
    escalated = summary.get("escalations_sent", 0)
    return RedirectResponse(
        url=f"/settings/reminders?ran=1&sent={sent}&escalated={escalated}",
        status_code=303,
    )
