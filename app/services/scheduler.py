"""
Background scheduler for automated reminder processing.

Uses APScheduler to run reminder checks on a configurable interval.
Integrates with FastAPI lifespan for clean startup/shutdown.
"""

import logging
import os

from apscheduler.schedulers.background import BackgroundScheduler

from models import SessionLocal
from app.services.reminder_service import process_reminders
from app.services.sla_service import check_and_notify_sla_breaches

logger = logging.getLogger(__name__)

# How often to check for due reminders (in minutes)
CHECK_INTERVAL_MINUTES = int(os.getenv("REMINDER_CHECK_INTERVAL", "60"))

scheduler = BackgroundScheduler()


def _run_reminder_check():
    """Scheduled job: process all due reminders."""
    db = SessionLocal()
    try:
        base_url = os.getenv("BASE_URL", "http://localhost:5000")
        summary = process_reminders(db, base_url=base_url)
        if summary.get("reminders_sent") or summary.get("escalations_sent"):
            logger.info(f"Scheduler reminder run: {summary}")
    except Exception as e:
        logger.error(f"Scheduler reminder error: {e}")
    finally:
        db.close()


def _run_sla_check():
    """Scheduled job: check for SLA breaches and warnings."""
    db = SessionLocal()
    try:
        result = check_and_notify_sla_breaches(db)
        if result.get("breaches") or result.get("warnings"):
            logger.info(f"Scheduler SLA check: {result}")
    except Exception as e:
        logger.error(f"Scheduler SLA check error: {e}")
    finally:
        db.close()


def start_scheduler():
    """Start the background scheduler."""
    scheduler.add_job(
        _run_reminder_check,
        "interval",
        minutes=CHECK_INTERVAL_MINUTES,
        id="reminder_check",
        replace_existing=True,
    )
    scheduler.add_job(
        _run_sla_check,
        "interval",
        minutes=CHECK_INTERVAL_MINUTES,
        id="sla_check",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(f"Scheduler started (checking every {CHECK_INTERVAL_MINUTES} minutes)")


def stop_scheduler():
    """Shut down the scheduler gracefully."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Reminder scheduler stopped")


def run_now():
    """Manually trigger a reminder check (for testing / admin use)."""
    db = SessionLocal()
    try:
        base_url = os.getenv("BASE_URL", "http://localhost:5000")
        return process_reminders(db, base_url=base_url)
    finally:
        db.close()


def run_sla_now():
    """Manually trigger an SLA check (for testing / admin use)."""
    db = SessionLocal()
    try:
        return check_and_notify_sla_breaches(db)
    finally:
        db.close()
