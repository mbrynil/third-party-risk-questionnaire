from fastapi import FastAPI
from datetime import datetime

from models import (
    init_db, get_db, seed_question_bank, seed_risk_statements, backfill_question_categories, SessionLocal,
    Assessment, Response,
    RESPONSE_STATUS_SUBMITTED,
    ASSESSMENT_STATUS_SENT, ASSESSMENT_STATUS_IN_PROGRESS, ASSESSMENT_STATUS_SUBMITTED,
)
from app.routers import home, vendor_facing, responses, assessments, templates_mgmt, vendors, decisions, risk_library

app = FastAPI(title="Third-Party Risk Questionnaire System")

init_db()
seed_question_bank()
seed_risk_statements()
backfill_question_categories()


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

app.include_router(home.router)
app.include_router(vendor_facing.router)
app.include_router(responses.router)
app.include_router(assessments.router)
app.include_router(templates_mgmt.router)
app.include_router(vendors.router)
app.include_router(decisions.router)
app.include_router(risk_library.router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)
