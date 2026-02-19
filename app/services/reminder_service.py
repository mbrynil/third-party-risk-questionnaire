"""
Automated reminder service for outstanding assessments.

Called periodically by the scheduler to:
1. Find assessments that need reminders
2. Send reminder emails
3. Escalate non-responsive vendors
4. Log all activity
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from models import (
    Assessment, ReminderConfig, ReminderLog, Vendor,
    ASSESSMENT_STATUS_SENT, ASSESSMENT_STATUS_DRAFT,
    REMINDER_TYPE_REMINDER, REMINDER_TYPE_ESCALATION, REMINDER_TYPE_FINAL,
    ensure_reminder_config,
)
from app.services.email_service import send_assessment_reminder, send_escalation_notice
from app.services.activity_service import log_activity
from app.services.notification_service import create_notification
from models import ACTIVITY_REMINDER_SENT, NOTIF_ESCALATION

logger = logging.getLogger(__name__)


def get_reminder_config(db: Session) -> ReminderConfig:
    """Get or create the global reminder configuration."""
    return ensure_reminder_config(db)


def get_assessments_needing_reminders(db: Session, config: ReminderConfig) -> list[dict]:
    """Find assessments that are due for a reminder.

    Returns a list of dicts with assessment info and computed fields.
    """
    if not config.enabled:
        return []

    now = datetime.utcnow()
    results = []

    # Find sent assessments that haven't been completed
    assessments = db.query(Assessment).filter(
        Assessment.status.in_([ASSESSMENT_STATUS_SENT, "IN_PROGRESS"]),
        Assessment.sent_at.isnot(None),
        Assessment.sent_to_email.isnot(None),
        Assessment.reminders_paused == False,
    ).all()

    for assessment in assessments:
        # Skip expired assessments
        if assessment.expires_at and assessment.expires_at < now:
            continue

        days_since_sent = (now - assessment.sent_at).days

        # Per-assessment overrides or global config
        eff_first_reminder = assessment.first_reminder_days if assessment.first_reminder_days is not None else config.first_reminder_days
        eff_frequency = assessment.reminder_frequency_days if assessment.reminder_frequency_days is not None else config.frequency_days
        eff_max = assessment.max_reminders if assessment.max_reminders is not None else config.max_reminders

        # Get reminder history for this assessment
        reminders_sent = db.query(ReminderLog).filter(
            ReminderLog.assessment_id == assessment.id,
            ReminderLog.reminder_type.in_([REMINDER_TYPE_REMINDER, REMINDER_TYPE_FINAL]),
        ).order_by(ReminderLog.sent_at.desc()).all()

        reminder_count = len(reminders_sent)

        # Check if max reminders reached
        if reminder_count >= eff_max:
            # Check if escalation is needed
            escalation_sent = db.query(ReminderLog).filter(
                ReminderLog.assessment_id == assessment.id,
                ReminderLog.reminder_type == REMINDER_TYPE_ESCALATION,
            ).first()

            if not escalation_sent and config.escalation_email:
                results.append({
                    "assessment": assessment,
                    "action": "escalate",
                    "reminder_count": reminder_count,
                    "days_waiting": days_since_sent,
                })
            continue

        # Determine if it's time for a reminder
        if reminder_count == 0:
            # First reminder: wait first_reminder_days after sent_at
            if days_since_sent < eff_first_reminder:
                continue
        else:
            # Subsequent reminders: wait frequency_days after last reminder
            last_reminder = reminders_sent[0]
            days_since_last = (now - last_reminder.sent_at).days
            if days_since_last < eff_frequency:
                continue

        # Check for final notice (close to expiry)
        action = "remind"
        if (assessment.expires_at
                and config.final_notice_days_before_expiry > 0
                and (assessment.expires_at - now).days <= config.final_notice_days_before_expiry
                and reminder_count >= 1):
            # Check if final notice already sent
            final_sent = db.query(ReminderLog).filter(
                ReminderLog.assessment_id == assessment.id,
                ReminderLog.reminder_type == REMINDER_TYPE_FINAL,
            ).first()
            if not final_sent:
                action = "final_notice"

        results.append({
            "assessment": assessment,
            "action": action,
            "reminder_count": reminder_count,
            "days_waiting": days_since_sent,
        })

    return results


def process_reminders(db: Session, base_url: str = "http://localhost:5000") -> dict:
    """Main entry point: check all assessments and send due reminders.

    Returns summary dict: {reminders_sent, escalations_sent, errors}
    """
    config = get_reminder_config(db)
    if not config.enabled:
        logger.info("Reminder system is disabled.")
        return {"reminders_sent": 0, "escalations_sent": 0, "skipped": "disabled"}

    due_items = get_assessments_needing_reminders(db, config)
    summary = {"reminders_sent": 0, "escalations_sent": 0, "errors": []}

    for item in due_items:
        assessment = item["assessment"]
        action = item["action"]

        try:
            if action == "escalate":
                _handle_escalation(db, assessment, item, config, base_url)
                summary["escalations_sent"] += 1

            elif action in ("remind", "final_notice"):
                _handle_reminder(db, assessment, item, config, base_url, is_final=(action == "final_notice"))
                summary["reminders_sent"] += 1

        except Exception as e:
            logger.error(f"Error processing reminder for assessment {assessment.id}: {e}")
            summary["errors"].append({"assessment_id": assessment.id, "error": str(e)})

    if summary["reminders_sent"] or summary["escalations_sent"]:
        logger.info(
            f"Reminder run complete: {summary['reminders_sent']} reminders, "
            f"{summary['escalations_sent']} escalations"
        )

    return summary


def _handle_reminder(
    db: Session, assessment: Assessment, item: dict,
    config: ReminderConfig, base_url: str, is_final: bool = False,
):
    """Send a reminder email and log it."""
    reminder_number = item["reminder_count"] + 1
    assessment_url = f"{base_url}/vendor/{assessment.token}"

    send_assessment_reminder(
        to_email=assessment.sent_to_email,
        to_name=assessment.company_name,
        vendor_name=assessment.company_name,
        assessment_title=assessment.title,
        assessment_url=assessment_url,
        reminder_number=reminder_number,
        days_waiting=item["days_waiting"],
        expires_at=assessment.expires_at,
    )

    log = ReminderLog(
        assessment_id=assessment.id,
        to_email=assessment.sent_to_email,
        reminder_number=reminder_number,
        reminder_type=REMINDER_TYPE_FINAL if is_final else REMINDER_TYPE_REMINDER,
    )
    db.add(log)
    if assessment.vendor_id:
        label = "Final notice" if is_final else f"Reminder #{reminder_number}"
        log_activity(db, assessment.vendor_id, ACTIVITY_REMINDER_SENT,
                     f"{label} sent to {assessment.sent_to_email} for '{assessment.title}'",
                     assessment_id=assessment.id)
    db.commit()

    logger.info(
        f"{'Final notice' if is_final else 'Reminder'} #{reminder_number} sent "
        f"for assessment {assessment.id} ({assessment.title}) to {assessment.sent_to_email}"
    )


def _handle_escalation(
    db: Session, assessment: Assessment, item: dict,
    config: ReminderConfig, base_url: str,
):
    """Send an escalation email to the configured analyst and log it."""
    vendor_profile_url = f"{base_url}/vendors/{assessment.vendor_id}" if assessment.vendor_id else base_url

    send_escalation_notice(
        to_email=config.escalation_email,
        vendor_name=assessment.company_name,
        assessment_title=assessment.title,
        vendor_profile_url=vendor_profile_url,
        reminder_count=item["reminder_count"],
        days_waiting=item["days_waiting"],
        sent_to_email=assessment.sent_to_email or "unknown",
    )

    log = ReminderLog(
        assessment_id=assessment.id,
        to_email=config.escalation_email,
        reminder_number=item["reminder_count"],
        reminder_type=REMINDER_TYPE_ESCALATION,
    )
    db.add(log)
    if assessment.vendor_id:
        create_notification(db, NOTIF_ESCALATION,
                            f"Escalation: {assessment.company_name} non-responsive after {item['reminder_count']} reminders",
                            link=f"/vendors/{assessment.vendor_id}",
                            vendor_id=assessment.vendor_id,
                            assessment_id=assessment.id)
    db.commit()

    logger.info(
        f"Escalation sent for assessment {assessment.id} ({assessment.title}) "
        f"to {config.escalation_email}"
    )


def get_reminder_history(db: Session, assessment_id: int) -> list[ReminderLog]:
    """Get all reminders sent for a specific assessment."""
    return db.query(ReminderLog).filter(
        ReminderLog.assessment_id == assessment_id,
    ).order_by(ReminderLog.sent_at.desc()).all()


def get_reminder_stats(db: Session) -> dict:
    """Get summary stats for the dashboard."""
    now = datetime.utcnow()

    awaiting = db.query(Assessment).filter(
        Assessment.status.in_([ASSESSMENT_STATUS_SENT, "IN_PROGRESS"]),
        Assessment.sent_at.isnot(None),
    ).all()

    awaiting_count = len(awaiting)
    overdue_count = 0
    longest_wait = 0

    for a in awaiting:
        days = (now - a.sent_at).days
        if days > longest_wait:
            longest_wait = days
        if days > 7:
            overdue_count += 1

    total_reminders = db.query(ReminderLog).filter(
        ReminderLog.reminder_type == REMINDER_TYPE_REMINDER,
    ).count()

    total_escalations = db.query(ReminderLog).filter(
        ReminderLog.reminder_type == REMINDER_TYPE_ESCALATION,
    ).count()

    return {
        "awaiting_response": awaiting_count,
        "overdue_responses": overdue_count,
        "longest_wait_days": longest_wait,
        "total_reminders_sent": total_reminders,
        "total_escalations": total_escalations,
    }
