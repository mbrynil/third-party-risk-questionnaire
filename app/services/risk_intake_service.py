"""Risk intake service — submit, review, and convert risk identification requests."""

from datetime import datetime
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from models import (
    RiskIntake, Risk, User,
    INTAKE_STATUS_SUBMITTED, INTAKE_STATUS_UNDER_REVIEW,
    INTAKE_STATUS_ACCEPTED, INTAKE_STATUS_REJECTED, INTAKE_STATUS_CONVERTED,
    RISK_STATUS_IDENTIFIED,
)
from app.services.risk_service import generate_risk_ref


# ── Ref generation ────────────────────────────────────────────────────────
def generate_intake_ref(db: Session) -> str:
    """Auto-generate RI-001, RI-002, etc."""
    existing = db.query(RiskIntake.intake_ref).all()
    max_num = 0
    for (ref,) in existing:
        try:
            num = int(ref.split("-")[-1])
            if num > max_num:
                max_num = num
        except (ValueError, IndexError):
            pass
    return f"RI-{max_num + 1:03d}"


# ── CRUD ──────────────────────────────────────────────────────────────────
def get_all_intakes(db: Session, status=None, submitter_id=None, reviewer_id=None, active_only=True):
    q = db.query(RiskIntake).options(
        joinedload(RiskIntake.submitter),
        joinedload(RiskIntake.reviewer),
    )
    if active_only:
        q = q.filter(RiskIntake.is_active == True)
    if status:
        q = q.filter(RiskIntake.status == status)
    if submitter_id:
        q = q.filter(RiskIntake.submitter_user_id == submitter_id)
    if reviewer_id:
        q = q.filter(RiskIntake.reviewer_user_id == reviewer_id)
    return q.order_by(RiskIntake.created_at.desc()).all()


def get_intake(db: Session, intake_id: int):
    return db.query(RiskIntake).options(
        joinedload(RiskIntake.submitter),
        joinedload(RiskIntake.suggested_owner),
        joinedload(RiskIntake.reviewer),
        joinedload(RiskIntake.converted_risk),
    ).filter(RiskIntake.id == intake_id).first()


def create_intake(db: Session, **kwargs):
    intake_ref = generate_intake_ref(db)
    intake = RiskIntake(
        intake_ref=intake_ref,
        title=kwargs.get("title", ""),
        description=kwargs.get("description"),
        submitter_user_id=kwargs.get("submitter_user_id"),
        risk_category=kwargs.get("risk_category"),
        risk_source=kwargs.get("risk_source"),
        status=INTAKE_STATUS_SUBMITTED,
        initial_severity=kwargs.get("initial_severity"),
        business_context=kwargs.get("business_context"),
        potential_impact=kwargs.get("potential_impact"),
        affected_assets=kwargs.get("affected_assets"),
        suggested_owner_user_id=kwargs.get("suggested_owner_user_id"),
    )
    db.add(intake)
    db.flush()
    return intake


def update_intake(db: Session, intake_id: int, **kwargs):
    intake = db.query(RiskIntake).filter(RiskIntake.id == intake_id).first()
    if not intake:
        return None
    for k, v in kwargs.items():
        if hasattr(intake, k):
            setattr(intake, k, v)
    db.flush()
    return intake


# ── Review workflow ───────────────────────────────────────────────────────
def review_intake(db: Session, intake_id: int, reviewer_user_id: int,
                  decision: str, reviewer_notes: str = None):
    """Review an intake.  decision = 'accept' or 'reject'."""
    intake = db.query(RiskIntake).filter(RiskIntake.id == intake_id).first()
    if not intake:
        return None

    if decision == "accept":
        intake.status = INTAKE_STATUS_ACCEPTED
    elif decision == "reject":
        intake.status = INTAKE_STATUS_REJECTED
    else:
        return intake  # invalid decision, no-op

    intake.reviewer_user_id = reviewer_user_id
    intake.reviewed_at = datetime.utcnow()
    intake.reviewer_notes = reviewer_notes
    db.flush()
    return intake


# ── Conversion ────────────────────────────────────────────────────────────
def convert_to_risk(db: Session, intake_id: int, owner_user_id: int = None):
    """Convert an accepted intake to a formal Risk record.

    Returns (intake, risk).
    """
    intake = db.query(RiskIntake).filter(RiskIntake.id == intake_id).first()
    if not intake:
        return None, None
    if intake.status != INTAKE_STATUS_ACCEPTED:
        return intake, None

    risk_ref = generate_risk_ref(db)
    risk = Risk(
        risk_ref=risk_ref,
        title=intake.title,
        description=intake.description,
        risk_category=intake.risk_category,
        risk_source=intake.risk_source,
        status=RISK_STATUS_IDENTIFIED,
        owner_user_id=owner_user_id or intake.suggested_owner_user_id,
    )
    db.add(risk)
    db.flush()

    intake.converted_risk_id = risk.id
    intake.status = INTAKE_STATUS_CONVERTED
    db.flush()

    return intake, risk


# ── Statistics ────────────────────────────────────────────────────────────
def get_intake_stats(db: Session) -> dict:
    """Aggregate intake stats."""
    intakes = db.query(RiskIntake).filter(RiskIntake.is_active == True).all()
    by_status = {}
    for intake in intakes:
        by_status[intake.status] = by_status.get(intake.status, 0) + 1

    pending_review = (
        by_status.get(INTAKE_STATUS_SUBMITTED, 0)
        + by_status.get(INTAKE_STATUS_UNDER_REVIEW, 0)
    )

    return {
        "total": len(intakes),
        "by_status": by_status,
        "pending_review": pending_review,
    }
