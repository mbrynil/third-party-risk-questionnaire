import os
import sys

# Add MSYS2 GTK3/Pango libraries to PATH for WeasyPrint PDF generation (Windows)
if sys.platform == "win32":
    _msys2_bin = r"C:\msys64\mingw64\bin"
    if os.path.isdir(_msys2_bin) and _msys2_bin not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _msys2_bin + os.pathsep + os.environ.get("PATH", "")

from contextlib import asynccontextmanager

from fastapi import FastAPI
from datetime import datetime

from models import (
    init_db, get_db, seed_question_bank, seed_risk_statements,
    backfill_question_categories, backfill_question_bank_item_ids,
    backfill_vendor_new_columns, backfill_decision_scores,
    backfill_template_columns, backfill_auth_columns,
    seed_default_templates, seed_default_admin,
    SessionLocal,
    Assessment, Response, User, ensure_reminder_config,
    RESPONSE_STATUS_SUBMITTED,
    ASSESSMENT_STATUS_SENT, ASSESSMENT_STATUS_IN_PROGRESS, ASSESSMENT_STATUS_SUBMITTED,
)
from app.routers import home, vendor_facing, responses, assessments, templates_mgmt, vendors, decisions, risk_library, question_bank, remediations, settings, notifications, onboarding, admin
from app.routers import auth as auth_router
from app.services.auth_service import get_current_user
from app.services.scheduler import start_scheduler, stop_scheduler

init_db()
backfill_vendor_new_columns()
backfill_template_columns()
backfill_auth_columns()
seed_question_bank()
seed_risk_statements()
seed_default_templates()
seed_default_admin()
backfill_question_categories()
backfill_question_bank_item_ids()
backfill_decision_scores()

# Ensure default reminder config exists
_db = SessionLocal()
try:
    ensure_reminder_config(_db)
finally:
    _db.close()


@asynccontextmanager
async def lifespan(app):
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="Third-Party Risk Questionnaire System", lifespan=lifespan)


@app.middleware("http")
async def inject_current_user(request, call_next):
    """Make current_user available to templates via request.state."""
    db = SessionLocal()
    try:
        request.state.current_user = get_current_user(request, db)
    finally:
        db.close()
    response = await call_next(request)
    return response


def fix_stuck_assessment_statuses():
    """Fix assessments stuck at SENT/IN_PROGRESS when they have submitted responses."""
    db = SessionLocal()
    try:
        stuck_assessments = db.query(Assessment).filter(
            Assessment.status.in_([ASSESSMENT_STATUS_SENT, ASSESSMENT_STATUS_IN_PROGRESS])
        ).all()

        for a in stuck_assessments:
            submitted_responses = [r for r in a.responses if r.status == RESPONSE_STATUS_SUBMITTED]
            if submitted_responses:
                latest = max(submitted_responses, key=lambda r: r.submitted_at or datetime.min)
                a.status = ASSESSMENT_STATUS_SUBMITTED
                a.submitted_at = latest.submitted_at

        db.commit()
    finally:
        db.close()

fix_stuck_assessment_statuses()

app.include_router(auth_router.router)
app.include_router(home.router)
app.include_router(vendor_facing.router)
app.include_router(responses.router)
app.include_router(assessments.router)
app.include_router(templates_mgmt.router)
app.include_router(vendors.router)
app.include_router(decisions.router)
app.include_router(risk_library.router)
app.include_router(question_bank.router)
app.include_router(remediations.router)
app.include_router(settings.router)
app.include_router(notifications.router)
app.include_router(onboarding.router)
app.include_router(admin.router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)
