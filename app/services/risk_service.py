"""Risk register service — CRUD, assessment, treatment, mappings, snapshots."""

from datetime import datetime
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from models import (
    Risk, RiskControlMapping, RiskPolicyMapping, OrgRiskSnapshot,
    User, Control, Policy,
    RISK_STATUS_IDENTIFIED, RISK_STATUS_ASSESSED, RISK_STATUS_TREATING,
    RISK_STATUS_ACCEPTED, RISK_STATUS_CLOSED,
    VALID_RISK_STATUSES, VALID_TREATMENT_TYPES, VALID_TREATMENT_STATUSES,
    get_risk_level_label, RISK_LEVEL_COLORS,
)


def generate_risk_ref(db: Session) -> str:
    """Auto-generate RISK-### reference."""
    existing = db.query(Risk.risk_ref).all()
    max_num = 0
    for (ref,) in existing:
        try:
            num = int(ref.split("-")[-1])
            if num > max_num:
                max_num = num
        except (ValueError, IndexError):
            pass
    return f"RISK-{max_num + 1:03d}"


def get_all_risks(db: Session, status=None, category=None, source=None, owner_id=None, risk_level=None, active_only=True):
    q = db.query(Risk)
    if active_only:
        q = q.filter(Risk.is_active == True)
    if status:
        q = q.filter(Risk.status == status)
    if category:
        q = q.filter(Risk.risk_category == category)
    if source:
        q = q.filter(Risk.risk_source == source)
    if owner_id:
        q = q.filter(Risk.owner_user_id == owner_id)
    risks = q.order_by(Risk.risk_ref).all()
    if risk_level:
        risks = [r for r in risks if get_risk_level_label(r.inherent_risk_score) == risk_level]
    return risks


def get_risk(db: Session, risk_id: int):
    return db.query(Risk).options(
        joinedload(Risk.owner),
        joinedload(Risk.control_mappings).joinedload(RiskControlMapping.control),
        joinedload(Risk.policy_mappings).joinedload(RiskPolicyMapping.policy),
        joinedload(Risk.snapshots),
    ).filter(Risk.id == risk_id).first()


def create_risk(db: Session, **kwargs):
    risk_ref = generate_risk_ref(db)
    likelihood = kwargs.get("inherent_likelihood")
    impact = kwargs.get("inherent_impact")
    score = (likelihood or 0) * (impact or 0) if likelihood and impact else None

    risk = Risk(
        risk_ref=risk_ref,
        title=kwargs.get("title", ""),
        description=kwargs.get("description"),
        risk_category=kwargs.get("risk_category"),
        risk_source=kwargs.get("risk_source"),
        status=RISK_STATUS_IDENTIFIED,
        owner_user_id=kwargs.get("owner_user_id"),
        inherent_likelihood=likelihood,
        inherent_impact=impact,
        inherent_risk_score=score,
        risk_appetite_threshold=kwargs.get("risk_appetite_threshold", 10),
    )
    db.add(risk)
    db.flush()
    return risk


def update_risk(db: Session, risk_id: int, **kwargs):
    risk = db.query(Risk).filter(Risk.id == risk_id).first()
    if not risk:
        return None
    for k, v in kwargs.items():
        if hasattr(risk, k):
            setattr(risk, k, v)
    # Recompute scores
    if risk.inherent_likelihood and risk.inherent_impact:
        risk.inherent_risk_score = risk.inherent_likelihood * risk.inherent_impact
    if risk.residual_likelihood and risk.residual_impact:
        risk.residual_risk_score = risk.residual_likelihood * risk.residual_impact
    db.flush()
    return risk


def delete_risk(db: Session, risk_id: int):
    risk = db.query(Risk).filter(Risk.id == risk_id).first()
    if not risk:
        return False
    risk.is_active = False
    db.flush()
    return True


def assess_risk(db: Session, risk_id: int, likelihood: int, impact: int):
    risk = db.query(Risk).filter(Risk.id == risk_id).first()
    if not risk:
        return None
    risk.inherent_likelihood = likelihood
    risk.inherent_impact = impact
    risk.inherent_risk_score = likelihood * impact
    if risk.status == RISK_STATUS_IDENTIFIED:
        risk.status = RISK_STATUS_ASSESSED
    db.flush()
    return risk


def set_treatment(db: Session, risk_id: int, treatment_type: str, plan: str = None, due_date=None):
    risk = db.query(Risk).filter(Risk.id == risk_id).first()
    if not risk:
        return None
    risk.treatment_type = treatment_type
    risk.treatment_plan = plan
    risk.treatment_due_date = due_date
    risk.treatment_status = "NOT_STARTED"
    if risk.status in (RISK_STATUS_IDENTIFIED, RISK_STATUS_ASSESSED):
        risk.status = RISK_STATUS_TREATING
    db.flush()
    return risk


def accept_risk(db: Session, risk_id: int):
    risk = db.query(Risk).filter(Risk.id == risk_id).first()
    if risk:
        risk.status = RISK_STATUS_ACCEPTED
        risk.treatment_type = "ACCEPT"
        db.flush()
    return risk


def close_risk(db: Session, risk_id: int):
    risk = db.query(Risk).filter(Risk.id == risk_id).first()
    if risk:
        risk.status = RISK_STATUS_CLOSED
        db.flush()
    return risk


def reassess_risk(db: Session, risk_id: int, residual_likelihood: int, residual_impact: int):
    risk = db.query(Risk).filter(Risk.id == risk_id).first()
    if not risk:
        return None
    risk.residual_likelihood = residual_likelihood
    risk.residual_impact = residual_impact
    risk.residual_risk_score = residual_likelihood * residual_impact
    db.flush()
    return risk


def set_control_mappings(db: Session, risk_id: int, control_ids: list):
    db.query(RiskControlMapping).filter(RiskControlMapping.risk_id == risk_id).delete()
    for cid in control_ids:
        db.add(RiskControlMapping(risk_id=risk_id, control_id=cid))
    db.flush()


def set_policy_mappings(db: Session, risk_id: int, policy_ids: list):
    db.query(RiskPolicyMapping).filter(RiskPolicyMapping.risk_id == risk_id).delete()
    for pid in policy_ids:
        db.add(RiskPolicyMapping(risk_id=risk_id, policy_id=pid))
    db.flush()


def take_snapshot(db: Session, risk_id: int):
    risk = db.query(Risk).filter(Risk.id == risk_id).first()
    if not risk:
        return None
    snap = OrgRiskSnapshot(
        risk_id=risk_id,
        inherent_score=risk.inherent_risk_score,
        residual_score=risk.residual_risk_score,
        status=risk.status,
        treatment_type=risk.treatment_type,
    )
    db.add(snap)
    db.flush()
    return snap


def get_heatmap_data(db: Session):
    """Return 5x5 matrix with risk counts per cell (likelihood x impact)."""
    risks = db.query(Risk).filter(Risk.is_active == True).all()
    matrix = {}
    for l in range(1, 6):
        for i in range(1, 6):
            matrix[(l, i)] = []
    for r in risks:
        if r.inherent_likelihood and r.inherent_impact:
            key = (r.inherent_likelihood, r.inherent_impact)
            if key in matrix:
                matrix[key].append(r)
    return matrix
