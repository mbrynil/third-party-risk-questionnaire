from datetime import datetime
from sqlalchemy.orm import Session
from models import (
    AssessmentDecision, DECISION_STATUS_DRAFT, DECISION_STATUS_FINAL,
    DECISION_STATUS_PENDING_APPROVAL,
)


def get_or_create_decision(db: Session, assessment_id: int, vendor_id: int) -> AssessmentDecision:
    """Get existing decision or create a new draft."""
    decision = db.query(AssessmentDecision).filter(
        AssessmentDecision.assessment_id == assessment_id
    ).first()

    if not decision:
        decision = AssessmentDecision(
            vendor_id=vendor_id,
            assessment_id=assessment_id,
            status=DECISION_STATUS_DRAFT,
        )
        db.add(decision)
        db.commit()
        db.refresh(decision)

    return decision


def save_decision(
    db: Session,
    decision: AssessmentDecision,
    action: str,
    data_sensitivity: str | None = None,
    business_criticality: str | None = None,
    impact_rating: str | None = None,
    likelihood_rating: str | None = None,
    overall_risk_rating: str | None = None,
    decision_outcome: str | None = None,
    rationale: str | None = None,
    key_findings: str | None = None,
    remediation_required: str | None = None,
    next_review_date: str | None = None,
) -> tuple[bool, str | None]:
    """Update decision fields and optionally finalize.

    Returns (success, error_message).
    """
    if decision.status == DECISION_STATUS_FINAL:
        return False, "Assessment already finalized"

    if decision.status == DECISION_STATUS_PENDING_APPROVAL:
        return False, "Decision is pending approval and cannot be edited"

    decision.data_sensitivity = data_sensitivity or None
    decision.business_criticality = business_criticality or None
    decision.impact_rating = impact_rating or None
    decision.likelihood_rating = likelihood_rating or None
    decision.overall_risk_rating = overall_risk_rating or None
    decision.decision_outcome = decision_outcome or None
    decision.rationale = rationale.strip() if rationale else None
    decision.key_findings = key_findings.strip() if key_findings else None
    decision.remediation_required = remediation_required.strip() if remediation_required else None

    if next_review_date:
        try:
            decision.next_review_date = datetime.strptime(next_review_date, "%Y-%m-%d")
        except ValueError:
            decision.next_review_date = None
    else:
        decision.next_review_date = None

    if action == "finalize":
        required = [
            data_sensitivity, business_criticality, impact_rating,
            likelihood_rating, overall_risk_rating, decision_outcome,
        ]
        if not all(required):
            return False, "Please fill all required fields before finalizing"
        decision.status = DECISION_STATUS_FINAL
        decision.finalized_at = datetime.utcnow()

    return True, None


def requires_tier1_approval(vendor) -> bool:
    """Check if vendor is Tier 1 and requires maker/checker approval."""
    from app.services.tiering import get_effective_tier
    tier = get_effective_tier(vendor)
    return tier == "Tier 1"


def submit_for_approval(decision: AssessmentDecision):
    """Move decision to PENDING_APPROVAL state for maker/checker flow."""
    decision.status = DECISION_STATUS_PENDING_APPROVAL
    decision.requires_approval = True
    decision.approval_status = "PENDING"
    decision.finalized_at = datetime.utcnow()


def approve_decision(db: Session, decision: AssessmentDecision, approved_by_id: int,
                     approval_notes: str = None):
    """Admin approves a pending decision → FINAL."""
    decision.status = DECISION_STATUS_FINAL
    decision.approval_status = "APPROVED"
    decision.approved_by_id = approved_by_id
    decision.approval_notes = approval_notes
    decision.approved_at = datetime.utcnow()


def reject_decision(db: Session, decision: AssessmentDecision, approved_by_id: int,
                    approval_notes: str = None):
    """Admin rejects a pending decision → back to DRAFT."""
    decision.status = DECISION_STATUS_DRAFT
    decision.approval_status = "REJECTED"
    decision.approved_by_id = approved_by_id
    decision.approval_notes = approval_notes
    decision.approved_at = datetime.utcnow()
    decision.requires_approval = False
    decision.finalized_at = None
