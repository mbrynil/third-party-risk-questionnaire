"""Risk dashboard aggregations — KPIs, heatmap, top risks, trends."""

from sqlalchemy.orm import Session
from sqlalchemy import func

from models import (
    Risk, OrgRiskSnapshot,
    RISK_STATUS_IDENTIFIED, RISK_STATUS_ASSESSED, RISK_STATUS_TREATING,
    RISK_STATUS_ACCEPTED, RISK_STATUS_CLOSED,
    VALID_RISK_STATUSES, RISK_STATUS_LABELS, RISK_STATUS_COLORS,
    VALID_TREATMENT_TYPES, TREATMENT_TYPE_LABELS,
    get_risk_level_label, RISK_LEVEL_COLORS,
)
from app.services.risk_service import get_heatmap_data


def get_risk_dashboard_data(db: Session) -> dict:
    risks = db.query(Risk).filter(Risk.is_active == True).all()
    total = len(risks)

    # By status
    by_status = {}
    for s in VALID_RISK_STATUSES:
        by_status[s] = sum(1 for r in risks if r.status == s)

    # By level
    by_level = {}
    for r in risks:
        level = get_risk_level_label(r.inherent_risk_score)
        by_level[level] = by_level.get(level, 0) + 1

    # By treatment
    by_treatment = {}
    for t in VALID_TREATMENT_TYPES:
        by_treatment[t] = sum(1 for r in risks if r.treatment_type == t)

    # Top risks (by inherent score, descending)
    top_risks = sorted(
        [r for r in risks if r.inherent_risk_score],
        key=lambda r: r.inherent_risk_score,
        reverse=True,
    )[:10]

    # Above appetite
    above_appetite = sum(
        1 for r in risks
        if r.inherent_risk_score and r.inherent_risk_score > (r.risk_appetite_threshold or 10)
    )

    # Heatmap
    heatmap = get_heatmap_data(db)

    return {
        "total": total,
        "by_status": by_status,
        "by_level": by_level,
        "by_treatment": by_treatment,
        "top_risks": top_risks,
        "above_appetite": above_appetite,
        "heatmap": heatmap,
        "status_labels": RISK_STATUS_LABELS,
        "status_colors": RISK_STATUS_COLORS,
        "treatment_labels": TREATMENT_TYPE_LABELS,
        "level_colors": RISK_LEVEL_COLORS,
    }
