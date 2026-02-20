"""SLA tracking service — compute SLA status, aggregate metrics, detect breaches."""

from datetime import datetime
from sqlalchemy.orm import Session

from models import (
    Assessment, AssessmentDecision, SLAConfig, ReminderConfig,
    Notification, VendorActivity,
    ASSESSMENT_STATUS_SENT, ASSESSMENT_STATUS_IN_PROGRESS,
    ASSESSMENT_STATUS_SUBMITTED, ASSESSMENT_STATUS_REVIEWED,
    DECISION_STATUS_FINAL,
    SLA_STATUS_ON_TRACK, SLA_STATUS_AT_RISK, SLA_STATUS_BREACHED,
    SLA_STATUS_COMPLETED, SLA_STATUS_NA,
    ACTIVITY_SLA_WARNING, ACTIVITY_SLA_BREACH,
    NOTIF_SLA_WARNING, NOTIF_SLA_BREACH,
    ensure_reminder_config,
)
from app.services.tiering import get_effective_tier


def _get_sla_config_map(db: Session) -> dict[str, SLAConfig]:
    """Return {tier_string: SLAConfig} for all enabled tiers."""
    configs = db.query(SLAConfig).filter(SLAConfig.enabled == True).all()
    return {c.tier: c for c in configs}


def is_sla_enabled(db: Session) -> bool:
    """Check if SLA tracking is globally enabled."""
    config = db.query(ReminderConfig).first()
    if config and hasattr(config, "sla_enabled"):
        return bool(config.sla_enabled)
    return True  # default on


def compute_sla_status(
    assessment: Assessment,
    sla_cfg: SLAConfig | None,
    now: datetime,
    decision: AssessmentDecision | None = None,
) -> dict:
    """Compute per-phase SLA status for an assessment.

    Returns dict with:
      response_phase: {status, days_elapsed, deadline_days, pct}
      review_phase: {status, days_elapsed, deadline_days, pct}
      overall: one of SLA_STATUS_*
    """
    result = {
        "response_phase": None,
        "review_phase": None,
        "overall": SLA_STATUS_NA,
    }

    if not sla_cfg:
        return result

    # Response phase: sent_at → submitted_at
    if assessment.sent_at:
        end_time = assessment.submitted_at or now
        days_elapsed = (end_time - assessment.sent_at).total_seconds() / 86400
        deadline = sla_cfg.response_deadline_days
        pct = (days_elapsed / deadline * 100) if deadline > 0 else 0
        threshold = sla_cfg.warning_threshold_pct

        if assessment.submitted_at:
            # Phase complete
            phase_status = SLA_STATUS_COMPLETED if days_elapsed <= deadline else SLA_STATUS_BREACHED
        else:
            # Phase in progress
            if days_elapsed > deadline:
                phase_status = SLA_STATUS_BREACHED
            elif pct >= threshold:
                phase_status = SLA_STATUS_AT_RISK
            else:
                phase_status = SLA_STATUS_ON_TRACK

        result["response_phase"] = {
            "status": phase_status,
            "days_elapsed": round(days_elapsed, 1),
            "deadline_days": deadline,
            "pct": round(pct, 1),
        }

    # Review phase: submitted_at → finalized_at
    if assessment.submitted_at:
        finalized_at = None
        if decision and decision.status == DECISION_STATUS_FINAL and decision.finalized_at:
            finalized_at = decision.finalized_at

        end_time = finalized_at or now
        days_elapsed = (end_time - assessment.submitted_at).total_seconds() / 86400
        deadline = sla_cfg.review_deadline_days
        pct = (days_elapsed / deadline * 100) if deadline > 0 else 0
        threshold = sla_cfg.warning_threshold_pct

        if finalized_at:
            phase_status = SLA_STATUS_COMPLETED if days_elapsed <= deadline else SLA_STATUS_BREACHED
        else:
            if days_elapsed > deadline:
                phase_status = SLA_STATUS_BREACHED
            elif pct >= threshold:
                phase_status = SLA_STATUS_AT_RISK
            else:
                phase_status = SLA_STATUS_ON_TRACK

        result["review_phase"] = {
            "status": phase_status,
            "days_elapsed": round(days_elapsed, 1),
            "deadline_days": deadline,
            "pct": round(pct, 1),
        }

    # Overall = worst of active phases
    statuses = []
    if result["response_phase"]:
        statuses.append(result["response_phase"]["status"])
    if result["review_phase"]:
        statuses.append(result["review_phase"]["status"])

    if not statuses:
        result["overall"] = SLA_STATUS_NA
    elif SLA_STATUS_BREACHED in statuses:
        result["overall"] = SLA_STATUS_BREACHED
    elif SLA_STATUS_AT_RISK in statuses:
        result["overall"] = SLA_STATUS_AT_RISK
    elif any(s == SLA_STATUS_ON_TRACK for s in statuses):
        result["overall"] = SLA_STATUS_ON_TRACK
    else:
        result["overall"] = SLA_STATUS_COMPLETED

    return result


def get_sla_summary(db: Session) -> dict:
    """Org-wide SLA aggregates."""
    if not is_sla_enabled(db):
        return {"enabled": False}

    sla_map = _get_sla_config_map(db)
    now = datetime.utcnow()

    # Active assessments (not DRAFT, not fully finalized)
    assessments = db.query(Assessment).filter(
        Assessment.status.in_([
            ASSESSMENT_STATUS_SENT, ASSESSMENT_STATUS_IN_PROGRESS,
            ASSESSMENT_STATUS_SUBMITTED, ASSESSMENT_STATUS_REVIEWED,
        ]),
        Assessment.sent_at != None,
    ).all()

    # Get decisions for these assessments
    a_ids = [a.id for a in assessments]
    decisions = {}
    if a_ids:
        for d in db.query(AssessmentDecision).filter(
            AssessmentDecision.assessment_id.in_(a_ids)
        ).all():
            decisions[d.assessment_id] = d

    breach_count = 0
    at_risk_count = 0
    response_days_list = []
    review_days_list = []

    for a in assessments:
        vendor = a.vendor
        tier = get_effective_tier(vendor) if vendor else None
        cfg = sla_map.get(tier) if tier else None
        decision = decisions.get(a.id)

        sla = compute_sla_status(a, cfg, now, decision)

        if sla["overall"] == SLA_STATUS_BREACHED:
            breach_count += 1
        elif sla["overall"] == SLA_STATUS_AT_RISK:
            at_risk_count += 1

        if sla["response_phase"] and sla["response_phase"]["status"] in (SLA_STATUS_COMPLETED, SLA_STATUS_BREACHED):
            response_days_list.append(sla["response_phase"]["days_elapsed"])
        if sla["review_phase"] and sla["review_phase"]["status"] in (SLA_STATUS_COMPLETED, SLA_STATUS_BREACHED):
            review_days_list.append(sla["review_phase"]["days_elapsed"])

    avg_response = round(sum(response_days_list) / len(response_days_list), 1) if response_days_list else None
    avg_review = round(sum(review_days_list) / len(review_days_list), 1) if review_days_list else None

    return {
        "enabled": True,
        "breach_count": breach_count,
        "at_risk_count": at_risk_count,
        "avg_response_days": avg_response,
        "avg_review_days": avg_review,
    }


def check_and_notify_sla_breaches(db: Session):
    """Scheduler job: find newly breached assessments, create notifications + activity."""
    if not is_sla_enabled(db):
        return {"checked": 0, "new_breaches": 0}

    sla_map = _get_sla_config_map(db)
    now = datetime.utcnow()

    # Only check active (non-finalized) assessments
    assessments = db.query(Assessment).filter(
        Assessment.status.in_([
            ASSESSMENT_STATUS_SENT, ASSESSMENT_STATUS_IN_PROGRESS,
            ASSESSMENT_STATUS_SUBMITTED,
        ]),
        Assessment.sent_at != None,
    ).all()

    a_ids = [a.id for a in assessments]
    decisions = {}
    if a_ids:
        for d in db.query(AssessmentDecision).filter(
            AssessmentDecision.assessment_id.in_(a_ids)
        ).all():
            decisions[d.assessment_id] = d

    # Get existing breach notifications to avoid duplicates
    existing_breach_notifs = set()
    if a_ids:
        for n in db.query(Notification).filter(
            Notification.notification_type == NOTIF_SLA_BREACH,
            Notification.assessment_id.in_(a_ids),
        ).all():
            existing_breach_notifs.add(n.assessment_id)

    existing_warning_notifs = set()
    if a_ids:
        for n in db.query(Notification).filter(
            Notification.notification_type == NOTIF_SLA_WARNING,
            Notification.assessment_id.in_(a_ids),
        ).all():
            existing_warning_notifs.add(n.assessment_id)

    new_breaches = 0
    new_warnings = 0

    for a in assessments:
        vendor = a.vendor
        tier = get_effective_tier(vendor) if vendor else None
        cfg = sla_map.get(tier) if tier else None
        decision = decisions.get(a.id)

        sla = compute_sla_status(a, cfg, now, decision)

        if sla["overall"] == SLA_STATUS_BREACHED and a.id not in existing_breach_notifs:
            db.add(Notification(
                notification_type=NOTIF_SLA_BREACH,
                message=f"SLA breached for {a.company_name}: {a.title}",
                link=f"/assessments/{a.id}/decision" if a.status == ASSESSMENT_STATUS_SUBMITTED else f"/assessments/tracker",
                vendor_id=a.vendor_id,
                assessment_id=a.id,
            ))
            if a.vendor_id:
                db.add(VendorActivity(
                    vendor_id=a.vendor_id,
                    activity_type=ACTIVITY_SLA_BREACH,
                    description=f"SLA breached for assessment '{a.title}'",
                    assessment_id=a.id,
                ))
            new_breaches += 1

        elif sla["overall"] == SLA_STATUS_AT_RISK and a.id not in existing_warning_notifs:
            db.add(Notification(
                notification_type=NOTIF_SLA_WARNING,
                message=f"SLA at risk for {a.company_name}: {a.title}",
                link=f"/assessments/tracker",
                vendor_id=a.vendor_id,
                assessment_id=a.id,
            ))
            new_warnings += 1

    if new_breaches or new_warnings:
        db.commit()

    return {"checked": len(assessments), "new_breaches": new_breaches, "new_warnings": new_warnings}
