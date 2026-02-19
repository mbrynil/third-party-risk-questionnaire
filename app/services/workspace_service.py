"""Personal workspace service — aggregates data for My Workspace dashboard."""

from datetime import datetime, date, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import or_

from models import (
    User, Vendor, Assessment, AssessmentDecision, RemediationItem,
    VendorActivity, VENDOR_STATUS_ACTIVE,
    ASSESSMENT_STATUS_DRAFT, ASSESSMENT_STATUS_SENT,
    ASSESSMENT_STATUS_IN_PROGRESS, ASSESSMENT_STATUS_SUBMITTED,
    ASSESSMENT_STATUS_REVIEWED,
    DECISION_STATUS_FINAL,
    REMEDIATION_STATUS_CLOSED, REMEDIATION_STATUS_VERIFIED,
    ACTIVITY_ICONS, ACTIVITY_COLORS,
)
from app.services.tiering import get_effective_tier, TIER_COLORS
from app.services.portfolio import RISK_LABELS, DECISION_LABELS


def get_workspace_data(db: Session, user: User) -> dict:
    """Return everything the personal workspace dashboard needs."""
    today = date.today()
    now = datetime.utcnow()

    # --- My Vendors ---
    my_vendors = db.query(Vendor).filter(
        Vendor.assigned_analyst_id == user.id,
        Vendor.status == VENDOR_STATUS_ACTIVE,
    ).order_by(Vendor.name).all()
    my_vendor_ids = [v.id for v in my_vendors]

    # --- Latest finalized decisions for my vendors ---
    my_decisions = {}
    if my_vendor_ids:
        decisions = (
            db.query(AssessmentDecision)
            .filter(
                AssessmentDecision.vendor_id.in_(my_vendor_ids),
                AssessmentDecision.status == DECISION_STATUS_FINAL,
            )
            .order_by(AssessmentDecision.finalized_at.desc())
            .all()
        )
        for d in decisions:
            if d.vendor_id not in my_decisions:
                my_decisions[d.vendor_id] = d

    # --- Assessments for my vendors ---
    my_assessments = []
    if my_vendor_ids:
        my_assessments = db.query(Assessment).filter(
            Assessment.vendor_id.in_(my_vendor_ids),
        ).all()

    # --- Remediations assigned to me or for my vendors ---
    my_remediations = []
    if my_vendor_ids:
        my_remediations = db.query(RemediationItem).filter(
            or_(
                RemediationItem.assigned_to_user_id == user.id,
                RemediationItem.vendor_id.in_(my_vendor_ids),
            ),
            RemediationItem.status.notin_([REMEDIATION_STATUS_CLOSED, REMEDIATION_STATUS_VERIFIED]),
        ).all()

    # Also get remediations assigned directly to me (even outside my vendors)
    direct_remediations = db.query(RemediationItem).filter(
        RemediationItem.assigned_to_user_id == user.id,
        RemediationItem.status.notin_([REMEDIATION_STATUS_CLOSED, REMEDIATION_STATUS_VERIFIED]),
    ).all()
    # Merge without duplicates
    seen_rem_ids = {r.id for r in my_remediations}
    for r in direct_remediations:
        if r.id not in seen_rem_ids:
            my_remediations.append(r)
            seen_rem_ids.add(r.id)

    # ===================== PERSONAL KPIs =====================
    pending_reviews = sum(
        1 for a in my_assessments if a.status == ASSESSMENT_STATUS_SUBMITTED
    )

    open_remediations = len(my_remediations)

    overdue_remediations = sum(
        1 for r in my_remediations if r.due_date and r.due_date < now
    )
    overdue_vendor_reviews = sum(
        1 for d in my_decisions.values()
        if d.next_review_date and d.next_review_date.date() < today
    )
    overdue_items = overdue_remediations + overdue_vendor_reviews

    kpis = {
        "my_vendors": len(my_vendors),
        "pending_reviews": pending_reviews,
        "open_remediations": open_remediations,
        "overdue_items": overdue_items,
    }

    # ===================== ACTION ITEMS =====================
    action_items = []

    # P1: Overdue remediations assigned to me
    for r in my_remediations:
        if r.assigned_to_user_id == user.id and r.due_date and r.due_date < now:
            days_over = (now - r.due_date).days
            action_items.append({
                "priority": 1,
                "type": "overdue_remediation",
                "icon": "bi-exclamation-triangle-fill",
                "color": "#dc3545",
                "title": r.title[:80],
                "subtitle": f"Overdue by {days_over} day{'s' if days_over != 1 else ''}" + (f" — {r.vendor.name}" if r.vendor else ""),
                "link": f"/vendors/{r.vendor_id}/remediations",
                "due_info": r.due_date.strftime("%Y-%m-%d"),
            })

    # P2: Assessments awaiting review (SUBMITTED)
    for a in my_assessments:
        if a.status == ASSESSMENT_STATUS_SUBMITTED:
            action_items.append({
                "priority": 2,
                "type": "awaiting_review",
                "icon": "bi-clipboard-check",
                "color": "#fd7e14",
                "title": f"{a.company_name}: {a.title}",
                "subtitle": "Submitted — awaiting your review",
                "link": f"/responses/{a.id}",
                "due_info": a.submitted_at.strftime("%Y-%m-%d") if a.submitted_at else None,
            })

    # P3: Overdue vendor reviews
    for vid, d in my_decisions.items():
        if d.next_review_date and d.next_review_date.date() < today:
            days_over = (today - d.next_review_date.date()).days
            vendor = next((v for v in my_vendors if v.id == vid), None)
            action_items.append({
                "priority": 3,
                "type": "overdue_review",
                "icon": "bi-calendar-x",
                "color": "#dc3545",
                "title": f"{vendor.name if vendor else 'Vendor'} — review overdue",
                "subtitle": f"Due {d.next_review_date.strftime('%Y-%m-%d')} ({days_over} day{'s' if days_over != 1 else ''} ago)",
                "link": f"/vendors/{vid}",
                "due_info": d.next_review_date.strftime("%Y-%m-%d"),
            })

    # P4: Open remediations (not overdue) assigned to me
    for r in my_remediations:
        if r.assigned_to_user_id == user.id and (not r.due_date or r.due_date >= now):
            action_items.append({
                "priority": 4,
                "type": "open_remediation",
                "icon": "bi-wrench",
                "color": "#f59e0b",
                "title": r.title[:80],
                "subtitle": (f"Due {r.due_date.strftime('%Y-%m-%d')}" if r.due_date else "No due date") + (f" — {r.vendor.name}" if r.vendor else ""),
                "link": f"/vendors/{r.vendor_id}/remediations",
                "due_info": r.due_date.strftime("%Y-%m-%d") if r.due_date else None,
            })

    # P5: Awaiting vendor response (SENT / IN_PROGRESS)
    for a in my_assessments:
        if a.status in (ASSESSMENT_STATUS_SENT, ASSESSMENT_STATUS_IN_PROGRESS):
            action_items.append({
                "priority": 5,
                "type": "awaiting_response",
                "icon": "bi-hourglass-split",
                "color": "#0d6efd",
                "title": f"{a.company_name}: {a.title}",
                "subtitle": f"Status: {a.status.replace('_', ' ').title()}",
                "link": f"/assessments/{a.id}/manage",
                "due_info": None,
            })

    # P6: Upcoming reviews (within 30 days)
    upcoming_threshold = today + timedelta(days=30)
    for vid, d in my_decisions.items():
        if d.next_review_date and today <= d.next_review_date.date() <= upcoming_threshold:
            days_until = (d.next_review_date.date() - today).days
            vendor = next((v for v in my_vendors if v.id == vid), None)
            action_items.append({
                "priority": 6,
                "type": "upcoming_review",
                "icon": "bi-calendar-event",
                "color": "#0dcaf0",
                "title": f"{vendor.name if vendor else 'Vendor'} — review due soon",
                "subtitle": f"Due {d.next_review_date.strftime('%Y-%m-%d')} ({days_until} day{'s' if days_until != 1 else ''})",
                "link": f"/vendors/{vid}",
                "due_info": d.next_review_date.strftime("%Y-%m-%d"),
            })

    # P7: Draft assessments
    for a in my_assessments:
        if a.status == ASSESSMENT_STATUS_DRAFT:
            action_items.append({
                "priority": 7,
                "type": "draft_assessment",
                "icon": "bi-pencil-square",
                "color": "#6c757d",
                "title": f"{a.company_name}: {a.title}",
                "subtitle": "Draft — not yet sent",
                "link": f"/assessments/{a.id}/manage",
                "due_info": None,
            })

    action_items.sort(key=lambda x: x["priority"])

    # ===================== MY VENDORS TABLE =====================
    vendor_rows = []
    for v in my_vendors:
        decision = my_decisions.get(v.id)
        eff_tier = get_effective_tier(v)

        # Assessment status — latest assessment
        latest_assessment = None
        vendor_assessments = [a for a in my_assessments if a.vendor_id == v.id]
        if vendor_assessments:
            vendor_assessments.sort(key=lambda a: a.created_at or datetime.min, reverse=True)
            latest_assessment = vendor_assessments[0]

        # Open remediation count for this vendor
        vendor_open_rems = sum(1 for r in my_remediations if r.vendor_id == v.id)

        next_review = None
        is_overdue = False
        if decision and decision.next_review_date:
            next_review = decision.next_review_date.strftime("%Y-%m-%d")
            is_overdue = decision.next_review_date.date() < today

        vendor_rows.append({
            "id": v.id,
            "name": v.name,
            "tier": eff_tier,
            "tier_color": TIER_COLORS.get(eff_tier, "#6c757d") if eff_tier else None,
            "score": decision.overall_score if decision else None,
            "risk_rating": decision.overall_risk_rating if decision else None,
            "risk_rating_display": RISK_LABELS.get(decision.overall_risk_rating) if decision and decision.overall_risk_rating else None,
            "decision_outcome_display": DECISION_LABELS.get(decision.decision_outcome) if decision and decision.decision_outcome else None,
            "assessment_status": latest_assessment.status.replace("_", " ").title() if latest_assessment else None,
            "next_review": next_review,
            "is_overdue": is_overdue,
            "open_remediations": vendor_open_rems,
        })

    # ===================== RECENT ACTIVITY =====================
    activity_query = db.query(VendorActivity)
    if my_vendor_ids:
        activity_query = activity_query.filter(
            or_(
                VendorActivity.vendor_id.in_(my_vendor_ids),
                VendorActivity.user_id == user.id,
            )
        )
    else:
        activity_query = activity_query.filter(VendorActivity.user_id == user.id)

    recent_activities = activity_query.order_by(
        VendorActivity.created_at.desc()
    ).limit(15).all()

    activity_items = []
    for act in recent_activities:
        activity_items.append({
            "icon": ACTIVITY_ICONS.get(act.activity_type, "bi-circle"),
            "color": ACTIVITY_COLORS.get(act.activity_type, "#6c757d"),
            "description": act.description,
            "vendor_name": act.vendor.name if act.vendor else None,
            "vendor_id": act.vendor_id,
            "created_at": act.created_at,
            "user_name": act.user.display_name if act.user else None,
        })

    # ===================== ADMIN ORG OVERVIEW =====================
    org_overview = None
    if user.role == "admin":
        total_active = db.query(Vendor).filter(Vendor.status == VENDOR_STATUS_ACTIVE).count()
        total_pending = db.query(Assessment).filter(
            Assessment.status == ASSESSMENT_STATUS_SUBMITTED
        ).count()
        total_overdue_rems = db.query(RemediationItem).filter(
            RemediationItem.due_date < now,
            RemediationItem.status.notin_([REMEDIATION_STATUS_CLOSED, REMEDIATION_STATUS_VERIFIED]),
        ).count()
        org_overview = {
            "total_active_vendors": total_active,
            "total_pending_assessments": total_pending,
            "total_overdue_remediations": total_overdue_rems,
        }

    return {
        "kpis": kpis,
        "action_items": action_items,
        "vendor_rows": vendor_rows,
        "recent_activities": activity_items,
        "org_overview": org_overview,
    }
