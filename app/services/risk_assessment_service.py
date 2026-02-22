"""Risk assessment campaign service — CRUD, scoring, review, finalization, templates."""

from datetime import datetime
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from models import (
    RiskAssessment, RiskAssessmentItem, RiskAssessmentTemplate, Risk, User,
    OrgRiskSnapshot, ScenarioControlLink, RiskSimulationRun,
    RA_STATUS_DRAFT, RA_STATUS_IN_PROGRESS, RA_STATUS_UNDER_REVIEW,
    RA_STATUS_APPROVED, RA_STATUS_COMPLETED, RA_STATUS_CANCELLED,
    VALID_RA_STATUSES,
    RAI_STATUS_PENDING, RAI_STATUS_IN_PROGRESS, RAI_STATUS_ASSESSED, RAI_STATUS_REVIEWED,
    RISK_STATUS_IDENTIFIED, RISK_STATUS_ASSESSED,
    get_risk_level_label,
)


# ── Status transition map ────────────────────────────────────────────────
_VALID_TRANSITIONS = {
    RA_STATUS_DRAFT: [RA_STATUS_IN_PROGRESS, RA_STATUS_CANCELLED],
    RA_STATUS_IN_PROGRESS: [RA_STATUS_UNDER_REVIEW, RA_STATUS_CANCELLED],
    RA_STATUS_UNDER_REVIEW: [RA_STATUS_APPROVED, RA_STATUS_IN_PROGRESS, RA_STATUS_CANCELLED],
    RA_STATUS_APPROVED: [RA_STATUS_COMPLETED, RA_STATUS_CANCELLED],
    RA_STATUS_COMPLETED: [],
    RA_STATUS_CANCELLED: [],
}


# ── Ref generation ────────────────────────────────────────────────────────
def generate_assessment_ref(db: Session) -> str:
    """Auto-generate RA-001, RA-002, etc."""
    existing = db.query(RiskAssessment.assessment_ref).all()
    max_num = 0
    for (ref,) in existing:
        try:
            num = int(ref.split("-")[-1])
            if num > max_num:
                max_num = num
        except (ValueError, IndexError):
            pass
    return f"RA-{max_num + 1:03d}"


# ── CRUD ──────────────────────────────────────────────────────────────────
def get_all_assessments(db: Session, status=None, methodology=None, lead_id=None, active_only=True):
    q = db.query(RiskAssessment).options(joinedload(RiskAssessment.lead))
    if active_only:
        q = q.filter(RiskAssessment.is_active == True)
    if status:
        q = q.filter(RiskAssessment.status == status)
    if methodology:
        q = q.filter(RiskAssessment.methodology == methodology)
    if lead_id:
        q = q.filter(RiskAssessment.lead_user_id == lead_id)
    return q.order_by(RiskAssessment.created_at.desc()).all()


def get_assessment(db: Session, assessment_id: int):
    return db.query(RiskAssessment).options(
        joinedload(RiskAssessment.lead),
        joinedload(RiskAssessment.approver),
        joinedload(RiskAssessment.items).joinedload(RiskAssessmentItem.risk),
        joinedload(RiskAssessment.items).joinedload(RiskAssessmentItem.assessor),
        joinedload(RiskAssessment.items).joinedload(RiskAssessmentItem.reviewer),
        joinedload(RiskAssessment.items).joinedload(RiskAssessmentItem.simulation_runs),
    ).filter(RiskAssessment.id == assessment_id).first()


def create_assessment(db: Session, **kwargs):
    assessment_ref = generate_assessment_ref(db)
    assessment = RiskAssessment(
        assessment_ref=assessment_ref,
        title=kwargs.get("title", ""),
        description=kwargs.get("description"),
        scope=kwargs.get("scope"),
        methodology=kwargs.get("methodology", "QUALITATIVE"),
        status=RA_STATUS_DRAFT,
        lead_user_id=kwargs.get("lead_user_id"),
        assessment_period_start=kwargs.get("assessment_period_start"),
        assessment_period_end=kwargs.get("assessment_period_end"),
        due_date=kwargs.get("due_date"),
        risk_appetite_threshold=kwargs.get("risk_appetite_threshold", 10),
        notes=kwargs.get("notes"),
    )
    db.add(assessment)
    db.flush()
    return assessment


def create_from_template(db: Session, template_id: int, title: str, lead_user_id: int,
                         period_start=None, period_end=None, due_date=None):
    template = db.query(RiskAssessmentTemplate).filter(
        RiskAssessmentTemplate.id == template_id
    ).first()
    if not template:
        return None
    return create_assessment(
        db,
        title=title,
        methodology=template.methodology,
        risk_appetite_threshold=template.default_risk_appetite,
        scope=template.default_scope,
        lead_user_id=lead_user_id,
        assessment_period_start=period_start,
        assessment_period_end=period_end,
        due_date=due_date,
    )


def update_assessment(db: Session, assessment_id: int, **kwargs):
    assessment = db.query(RiskAssessment).filter(RiskAssessment.id == assessment_id).first()
    if not assessment:
        return None
    for k, v in kwargs.items():
        if hasattr(assessment, k):
            setattr(assessment, k, v)
    db.flush()
    return assessment


def delete_assessment(db: Session, assessment_id: int):
    assessment = db.query(RiskAssessment).filter(RiskAssessment.id == assessment_id).first()
    if not assessment:
        return False
    assessment.is_active = False
    db.flush()
    return True


# ── Status workflow ───────────────────────────────────────────────────────
def update_status(db: Session, assessment_id: int, new_status: str, user_id: int = None):
    """Advance assessment through the status workflow.

    Returns (assessment, error_message).  error_message is None on success.
    """
    assessment = db.query(RiskAssessment).filter(RiskAssessment.id == assessment_id).first()
    if not assessment:
        return None, "Assessment not found"

    if new_status not in VALID_RA_STATUSES:
        return assessment, f"Invalid status: {new_status}"

    allowed = _VALID_TRANSITIONS.get(assessment.status, [])
    if new_status not in allowed:
        return assessment, f"Cannot transition from {assessment.status} to {new_status}"

    assessment.status = new_status

    if new_status == RA_STATUS_APPROVED:
        assessment.approved_by_user_id = user_id
        assessment.approved_at = datetime.utcnow()
    elif new_status == RA_STATUS_COMPLETED:
        assessment.completed_at = datetime.utcnow()

    db.flush()
    return assessment, None


# ── Assessment items ──────────────────────────────────────────────────────
def add_risks_to_assessment(db: Session, assessment_id: int, risk_ids: list) -> int:
    """Add risks as assessment items, skipping duplicates.  Returns count added."""
    existing_risk_ids = {
        r for (r,) in db.query(RiskAssessmentItem.risk_id).filter(
            RiskAssessmentItem.assessment_id == assessment_id
        ).all()
    }
    max_order = db.query(func.max(RiskAssessmentItem.display_order)).filter(
        RiskAssessmentItem.assessment_id == assessment_id
    ).scalar() or 0

    added = 0
    for rid in risk_ids:
        if rid in existing_risk_ids:
            continue
        max_order += 1
        item = RiskAssessmentItem(
            assessment_id=assessment_id,
            risk_id=rid,
            status=RAI_STATUS_PENDING,
            display_order=max_order,
        )
        db.add(item)
        added += 1

    if added:
        db.flush()
    return added


def remove_item(db: Session, item_id: int) -> bool:
    item = db.query(RiskAssessmentItem).filter(RiskAssessmentItem.id == item_id).first()
    if not item:
        return False
    db.delete(item)
    db.flush()
    return True


def assign_assessors(db: Session, assessment_id: int, assignments: dict):
    """Bulk assign assessors.  assignments = {item_id: user_id}."""
    items = db.query(RiskAssessmentItem).filter(
        RiskAssessmentItem.assessment_id == assessment_id,
        RiskAssessmentItem.id.in_([int(k) for k in assignments.keys()]),
    ).all()
    for item in items:
        uid = assignments.get(item.id) or assignments.get(str(item.id))
        if uid is not None:
            item.assessor_user_id = int(uid)
    db.flush()


def get_item(db: Session, item_id: int):
    return db.query(RiskAssessmentItem).options(
        joinedload(RiskAssessmentItem.risk),
        joinedload(RiskAssessmentItem.assessor),
        joinedload(RiskAssessmentItem.reviewer),
    ).filter(RiskAssessmentItem.id == item_id).first()


# ── Scoring / assessment ─────────────────────────────────────────────────
def assess_item(db: Session, item_id: int, **kwargs):
    """Submit assessment scores for a single item.

    Qualitative: likelihood, impact -> inherent_score = L * I
                 residual_likelihood, residual_impact -> residual_score
    Quantitative: asset_value, exposure_factor -> SLE = AV * EF
                  annual_rate_of_occurrence -> ALE = SLE * ARO
    Semi-quantitative: all of the above.
    Also accepts: confidence_level, rationale, existing_controls_notes,
                  recommended_treatment, findings.
    """
    item = db.query(RiskAssessmentItem).filter(RiskAssessmentItem.id == item_id).first()
    if not item:
        return None

    # --- Qualitative scoring ---
    if "likelihood" in kwargs and kwargs["likelihood"] is not None:
        item.likelihood = int(kwargs["likelihood"])
    if "impact" in kwargs and kwargs["impact"] is not None:
        item.impact = int(kwargs["impact"])
    if item.likelihood and item.impact:
        item.inherent_score = item.likelihood * item.impact

    if "residual_likelihood" in kwargs and kwargs["residual_likelihood"] is not None:
        item.residual_likelihood = int(kwargs["residual_likelihood"])
    if "residual_impact" in kwargs and kwargs["residual_impact"] is not None:
        item.residual_impact = int(kwargs["residual_impact"])
    if item.residual_likelihood and item.residual_impact:
        item.residual_score = item.residual_likelihood * item.residual_impact

    # --- Quantitative scoring ---
    if "asset_value" in kwargs and kwargs["asset_value"] is not None:
        item.asset_value = float(kwargs["asset_value"])
    if "exposure_factor" in kwargs and kwargs["exposure_factor"] is not None:
        item.exposure_factor = float(kwargs["exposure_factor"])
    if item.asset_value is not None and item.exposure_factor is not None:
        item.single_loss_expectancy = item.asset_value * item.exposure_factor

    if "annual_rate_of_occurrence" in kwargs and kwargs["annual_rate_of_occurrence"] is not None:
        item.annual_rate_of_occurrence = float(kwargs["annual_rate_of_occurrence"])
    if item.single_loss_expectancy is not None and item.annual_rate_of_occurrence is not None:
        item.annualized_loss_expectancy = item.single_loss_expectancy * item.annual_rate_of_occurrence

    # --- FAIR factor inputs ---
    fair_fields = [
        "tef_min", "tef_likely", "tef_max",
        "vuln_min", "vuln_likely", "vuln_max",
        "plm_min", "plm_likely", "plm_max",
        "slm_min", "slm_likely", "slm_max",
    ]
    for field in fair_fields:
        if field in kwargs and kwargs[field] is not None:
            setattr(item, field, float(kwargs[field]))
        elif field in kwargs:
            setattr(item, field, None)

    # --- Scenario context ---
    if "asset_id" in kwargs:
        item.asset_id = int(kwargs["asset_id"]) if kwargs["asset_id"] else None
    if "vendor_link_id" in kwargs:
        item.vendor_link_id = int(kwargs["vendor_link_id"]) if kwargs["vendor_link_id"] else None

    # --- Treatment decision ---
    if "treatment_decision" in kwargs:
        item.treatment_decision = kwargs["treatment_decision"] or None
    if "treatment_decision_rationale" in kwargs:
        item.treatment_decision_rationale = kwargs["treatment_decision_rationale"] or None

    # --- Metadata ---
    for field in ("confidence_level", "rationale", "existing_controls_notes",
                  "recommended_treatment", "findings"):
        if field in kwargs:
            setattr(item, field, kwargs[field])

    item.status = RAI_STATUS_ASSESSED
    item.assessed_at = datetime.utcnow()
    db.flush()
    return item


def review_item(db: Session, item_id: int, reviewer_user_id: int,
                reviewer_notes: str = None, approved: bool = True):
    """Review an assessed item."""
    item = db.query(RiskAssessmentItem).filter(RiskAssessmentItem.id == item_id).first()
    if not item:
        return None
    item.status = RAI_STATUS_REVIEWED
    item.reviewed_by_user_id = reviewer_user_id
    item.reviewed_at = datetime.utcnow()
    item.reviewer_notes = reviewer_notes
    db.flush()
    return item


# ── Finalization ──────────────────────────────────────────────────────────
def finalize_assessment(db: Session, assessment_id: int) -> dict:
    """Apply assessment scores back to the linked Risk records.

    For each REVIEWED item:
    - Copy inherent/residual scores to the Risk
    - Take an OrgRiskSnapshot
    - Advance Risk status from IDENTIFIED -> ASSESSED if appropriate

    Returns dict with counts: {applied: N, skipped: N}.
    """
    assessment = db.query(RiskAssessment).options(
        joinedload(RiskAssessment.items).joinedload(RiskAssessmentItem.risk),
    ).filter(RiskAssessment.id == assessment_id).first()

    if not assessment:
        return {"applied": 0, "skipped": 0}

    applied = 0
    skipped = 0

    for item in assessment.items:
        if item.status != RAI_STATUS_REVIEWED:
            skipped += 1
            continue

        risk = item.risk
        if not risk:
            skipped += 1
            continue

        # Copy qualitative scores
        if item.likelihood is not None:
            risk.inherent_likelihood = item.likelihood
        if item.impact is not None:
            risk.inherent_impact = item.impact
        if item.inherent_score is not None:
            risk.inherent_risk_score = item.inherent_score

        if item.residual_likelihood is not None:
            risk.residual_likelihood = item.residual_likelihood
        if item.residual_impact is not None:
            risk.residual_impact = item.residual_impact
        if item.residual_score is not None:
            risk.residual_risk_score = item.residual_score

        # Advance status
        if risk.status == RISK_STATUS_IDENTIFIED:
            risk.status = RISK_STATUS_ASSESSED

        # Snapshot
        snap = OrgRiskSnapshot(
            risk_id=risk.id,
            inherent_score=risk.inherent_risk_score,
            residual_score=risk.residual_risk_score,
            status=risk.status,
            treatment_type=risk.treatment_type,
        )
        db.add(snap)
        applied += 1

    db.flush()
    return {"applied": applied, "skipped": skipped}


# ── Statistics ────────────────────────────────────────────────────────────
def get_assessment_stats(db: Session, assessment_id: int = None) -> dict:
    """Stats for one assessment or all active assessments."""
    if assessment_id:
        items_q = db.query(RiskAssessmentItem).filter(
            RiskAssessmentItem.assessment_id == assessment_id
        )
    else:
        # All items from active assessments
        active_ids = [
            a.id for a in db.query(RiskAssessment.id).filter(
                RiskAssessment.is_active == True
            ).all()
        ]
        items_q = db.query(RiskAssessmentItem).filter(
            RiskAssessmentItem.assessment_id.in_(active_ids)
        ) if active_ids else db.query(RiskAssessmentItem).filter(False)

    items = items_q.all()
    total = len(items)
    by_status = {}
    inherent_scores = []
    residual_scores = []
    high_risk = 0

    for item in items:
        by_status[item.status] = by_status.get(item.status, 0) + 1
        if item.inherent_score is not None:
            inherent_scores.append(item.inherent_score)
            if item.inherent_score >= 15:
                high_risk += 1
        if item.residual_score is not None:
            residual_scores.append(item.residual_score)

    reviewed_or_assessed = by_status.get(RAI_STATUS_ASSESSED, 0) + by_status.get(RAI_STATUS_REVIEWED, 0)
    completion_pct = round((reviewed_or_assessed / total) * 100, 1) if total else 0.0

    return {
        "total_items": total,
        "by_status": by_status,
        "completion_pct": completion_pct,
        "avg_inherent_score": round(sum(inherent_scores) / len(inherent_scores), 1) if inherent_scores else None,
        "avg_residual_score": round(sum(residual_scores) / len(residual_scores), 1) if residual_scores else None,
        "high_risk_count": high_risk,
    }


def get_dashboard_data(db: Session) -> dict:
    """Dashboard-level aggregations across all active assessments."""
    assessments = db.query(RiskAssessment).filter(RiskAssessment.is_active == True).all()

    by_status = {}
    by_methodology = {}
    for a in assessments:
        by_status[a.status] = by_status.get(a.status, 0) + 1
        by_methodology[a.methodology] = by_methodology.get(a.methodology, 0) + 1

    recent = db.query(RiskAssessment).options(
        joinedload(RiskAssessment.lead),
    ).filter(
        RiskAssessment.is_active == True,
    ).order_by(RiskAssessment.created_at.desc()).limit(10).all()

    active_campaign = db.query(RiskAssessment).options(
        joinedload(RiskAssessment.lead),
    ).filter(
        RiskAssessment.is_active == True,
        RiskAssessment.status == RA_STATUS_IN_PROGRESS,
    ).order_by(RiskAssessment.created_at.desc()).first()

    return {
        "total_assessments": len(assessments),
        "by_status": by_status,
        "by_methodology": by_methodology,
        "recent_assessments": recent,
        "active_campaign": active_campaign,
        "overall_stats": get_assessment_stats(db),
    }


# ── Templates ─────────────────────────────────────────────────────────────
def get_all_templates(db: Session):
    return db.query(RiskAssessmentTemplate).filter(
        RiskAssessmentTemplate.is_active == True
    ).order_by(RiskAssessmentTemplate.name).all()


def create_template(db: Session, **kwargs):
    template = RiskAssessmentTemplate(
        name=kwargs.get("name", ""),
        description=kwargs.get("description"),
        methodology=kwargs.get("methodology", "QUALITATIVE"),
        default_risk_appetite=kwargs.get("default_risk_appetite", 10),
        default_scope=kwargs.get("default_scope"),
        criteria_json=kwargs.get("criteria_json"),
        created_by_user_id=kwargs.get("created_by_user_id"),
    )
    db.add(template)
    db.flush()
    return template


def delete_template(db: Session, template_id: int) -> bool:
    template = db.query(RiskAssessmentTemplate).filter(
        RiskAssessmentTemplate.id == template_id
    ).first()
    if not template:
        return False
    db.delete(template)
    db.flush()
    return True


# ── Comparison / delta ────────────────────────────────────────────────────
def get_comparison_data(db: Session, assessment_id: int) -> dict:
    """Compare current assessment with the most recent previous one.

    Returns {current, previous, deltas} where deltas is a list of per-risk
    score changes.
    """
    current = get_assessment(db, assessment_id)
    if not current:
        return {"current": None, "previous": None, "deltas": []}

    previous = db.query(RiskAssessment).options(
        joinedload(RiskAssessment.items).joinedload(RiskAssessmentItem.risk),
    ).filter(
        RiskAssessment.id != assessment_id,
        RiskAssessment.is_active == True,
        RiskAssessment.status.in_([RA_STATUS_APPROVED, RA_STATUS_COMPLETED]),
        RiskAssessment.created_at < current.created_at,
    ).order_by(RiskAssessment.created_at.desc()).first()

    if not previous:
        return {"current": current, "previous": None, "deltas": []}

    # Build lookup of previous scores by risk_id
    prev_scores = {}
    for item in previous.items:
        if item.risk:
            prev_scores[item.risk_id] = {
                "risk_ref": item.risk.risk_ref,
                "risk_title": item.risk.title,
                "score": item.inherent_score,
            }

    deltas = []
    for item in current.items:
        if not item.risk:
            continue
        prev = prev_scores.get(item.risk_id)
        prev_score = prev["score"] if prev else None
        curr_score = item.inherent_score

        if curr_score is None and prev_score is None:
            continue

        change = None
        direction = "unchanged"
        if curr_score is not None and prev_score is not None:
            change = curr_score - prev_score
            if change > 0:
                direction = "increased"
            elif change < 0:
                direction = "decreased"
        elif curr_score is not None and prev_score is None:
            direction = "new"
        elif curr_score is None and prev_score is not None:
            direction = "removed"

        deltas.append({
            "risk_id": item.risk_id,
            "risk_ref": item.risk.risk_ref,
            "risk_title": item.risk.title,
            "prev_score": prev_score,
            "curr_score": curr_score,
            "change": change,
            "direction": direction,
        })

    return {"current": current, "previous": previous, "deltas": deltas}


# ── Simulation helpers ───────────────────────────────────────────────────

def get_item_with_simulation(db: Session, item_id: int):
    """Load an assessment item with control_links, simulation_runs, asset, vendor eagerly."""
    return db.query(RiskAssessmentItem).options(
        joinedload(RiskAssessmentItem.risk),
        joinedload(RiskAssessmentItem.assessor),
        joinedload(RiskAssessmentItem.reviewer),
        joinedload(RiskAssessmentItem.control_links).joinedload(ScenarioControlLink.implementation),
        joinedload(RiskAssessmentItem.simulation_runs),
        joinedload(RiskAssessmentItem.asset),
        joinedload(RiskAssessmentItem.vendor_link),
    ).filter(RiskAssessmentItem.id == item_id).first()


def get_executive_summary_data(db: Session, assessment_id: int) -> dict:
    """Aggregate simulation data across all items in an assessment for executive summary."""
    assessment = db.query(RiskAssessment).options(
        joinedload(RiskAssessment.lead),
        joinedload(RiskAssessment.items).joinedload(RiskAssessmentItem.risk),
        joinedload(RiskAssessment.items).joinedload(RiskAssessmentItem.simulation_runs),
    ).filter(RiskAssessment.id == assessment_id).first()

    if not assessment:
        return None

    items_data = []
    total_mean = 0.0
    total_p90 = 0.0
    simulated_count = 0

    for item in assessment.items:
        latest_run = None
        if item.simulation_runs:
            latest_run = item.simulation_runs[0]  # ordered desc by run_at

        item_info = {
            "item": item,
            "risk": item.risk,
            "latest_run": latest_run,
            "has_simulation": latest_run is not None,
        }
        items_data.append(item_info)

        if latest_run:
            total_mean += latest_run.mean_ale or 0.0
            total_p90 += latest_run.p90_ale or 0.0
            simulated_count += 1

    # Sort by P90 descending for top risks
    simulated_items = [d for d in items_data if d["has_simulation"]]
    top_risks_by_p90 = sorted(simulated_items, key=lambda d: d["latest_run"].p90_ale or 0, reverse=True)[:5]

    return {
        "assessment": assessment,
        "items_data": items_data,
        "total_mean_ale": round(total_mean, 2),
        "total_p90_ale": round(total_p90, 2),
        "simulated_count": simulated_count,
        "total_items": len(assessment.items),
        "top_risks_by_p90": top_risks_by_p90,
    }
