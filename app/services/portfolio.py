from datetime import datetime, date
from sqlalchemy.orm import Session

from models import (
    Vendor, Assessment, AssessmentDecision, Question, Response,
    VENDOR_STATUS_ACTIVE, VENDOR_STATUS_ARCHIVED,
    ASSESSMENT_STATUS_DRAFT, ASSESSMENT_STATUS_SENT,
    ASSESSMENT_STATUS_IN_PROGRESS, ASSESSMENT_STATUS_SUBMITTED,
    ASSESSMENT_STATUS_REVIEWED,
    DECISION_STATUS_FINAL,
    DECISION_APPROVE, DECISION_APPROVE_WITH_CONDITIONS,
    DECISION_NEEDS_FOLLOW_UP, DECISION_REJECT,
    RISK_LEVEL_VERY_LOW, RISK_LEVEL_LOW, RISK_LEVEL_MODERATE,
    RISK_LEVEL_HIGH, RISK_LEVEL_VERY_HIGH,
)
from app.services.scoring import compute_assessment_scores, suggest_risk_level


RISK_LABELS = {
    RISK_LEVEL_VERY_LOW: "Very Low",
    RISK_LEVEL_LOW: "Low",
    RISK_LEVEL_MODERATE: "Moderate",
    RISK_LEVEL_HIGH: "High",
    RISK_LEVEL_VERY_HIGH: "Very High",
}

RISK_COLORS = {
    RISK_LEVEL_VERY_LOW: "#198754",
    RISK_LEVEL_LOW: "#20c997",
    RISK_LEVEL_MODERATE: "#ffc107",
    RISK_LEVEL_HIGH: "#fd7e14",
    RISK_LEVEL_VERY_HIGH: "#dc3545",
}

DECISION_LABELS = {
    DECISION_APPROVE: "Approve",
    DECISION_APPROVE_WITH_CONDITIONS: "Approve With Conditions",
    DECISION_NEEDS_FOLLOW_UP: "Needs Follow Up",
    DECISION_REJECT: "Reject",
}

DECISION_COLORS = {
    DECISION_APPROVE: "#198754",
    DECISION_APPROVE_WITH_CONDITIONS: "#fd7e14",
    DECISION_NEEDS_FOLLOW_UP: "#ffc107",
    DECISION_REJECT: "#dc3545",
}

STATUS_LABELS = {
    ASSESSMENT_STATUS_DRAFT: "Draft",
    ASSESSMENT_STATUS_SENT: "Sent",
    ASSESSMENT_STATUS_IN_PROGRESS: "In Progress",
    ASSESSMENT_STATUS_SUBMITTED: "Submitted",
    ASSESSMENT_STATUS_REVIEWED: "Reviewed",
}

STATUS_COLORS = {
    ASSESSMENT_STATUS_DRAFT: "#6c757d",
    ASSESSMENT_STATUS_SENT: "#0d6efd",
    ASSESSMENT_STATUS_IN_PROGRESS: "#ffc107",
    ASSESSMENT_STATUS_SUBMITTED: "#0dcaf0",
    ASSESSMENT_STATUS_REVIEWED: "#198754",
}


def _score_color(score):
    if score >= 90:
        return "#198754"
    elif score >= 70:
        return "#20c997"
    elif score >= 50:
        return "#ffc107"
    else:
        return "#dc3545"


def get_portfolio_data(db: Session) -> dict:
    """Aggregate all data needed for the portfolio dashboard and print report."""

    vendors = db.query(Vendor).order_by(Vendor.name).all()
    all_assessments = db.query(Assessment).all()
    all_decisions = (
        db.query(AssessmentDecision)
        .filter(AssessmentDecision.status == DECISION_STATUS_FINAL)
        .order_by(AssessmentDecision.finalized_at.desc())
        .all()
    )

    # Latest finalized decision per vendor (most recent first already)
    latest_decision_by_vendor = {}
    for d in all_decisions:
        if d.vendor_id not in latest_decision_by_vendor:
            latest_decision_by_vendor[d.vendor_id] = d

    # Compute scores for each latest decision's assessment
    scores_by_vendor = {}
    for vendor_id, decision in latest_decision_by_vendor.items():
        assessment = decision.assessment
        if assessment:
            questions = (
                db.query(Question)
                .filter(Question.assessment_id == assessment.id)
                .order_by(Question.order)
                .all()
            )
            response = (
                db.query(Response)
                .filter(Response.assessment_id == assessment.id)
                .order_by(Response.submitted_at.desc())
                .first()
            )
            scores = compute_assessment_scores(questions, response)
            scores_by_vendor[vendor_id] = scores

    # --- KPIs ---
    active_vendors = [v for v in vendors if v.status == VENDOR_STATUS_ACTIVE]
    total_active_vendors = len(active_vendors)

    scored_vendors = [
        s["overall_score"]
        for s in scores_by_vendor.values()
        if s["overall_score"] is not None
    ]
    average_risk_score = (
        round(sum(scored_vendors) / len(scored_vendors), 1) if scored_vendors else None
    )

    pending_assessments = sum(
        1 for a in all_assessments if a.status == ASSESSMENT_STATUS_SUBMITTED
    )

    today = date.today()
    overdue_reviews = sum(
        1
        for d in latest_decision_by_vendor.values()
        if d.next_review_date and d.next_review_date.date() < today
    )

    # --- Risk Distribution (donut) ---
    risk_order = [
        RISK_LEVEL_VERY_LOW, RISK_LEVEL_LOW, RISK_LEVEL_MODERATE,
        RISK_LEVEL_HIGH, RISK_LEVEL_VERY_HIGH,
    ]
    risk_counts = {r: 0 for r in risk_order}
    for d in latest_decision_by_vendor.values():
        if d.overall_risk_rating and d.overall_risk_rating in risk_counts:
            risk_counts[d.overall_risk_rating] += 1

    risk_distribution = {
        "labels": [RISK_LABELS[r] for r in risk_order],
        "counts": [risk_counts[r] for r in risk_order],
        "colors": [RISK_COLORS[r] for r in risk_order],
    }

    # --- Decision Outcomes (donut) ---
    outcome_order = [
        DECISION_APPROVE, DECISION_APPROVE_WITH_CONDITIONS,
        DECISION_NEEDS_FOLLOW_UP, DECISION_REJECT,
    ]
    outcome_counts = {o: 0 for o in outcome_order}
    for d in latest_decision_by_vendor.values():
        if d.decision_outcome and d.decision_outcome in outcome_counts:
            outcome_counts[d.decision_outcome] += 1

    decision_outcomes = {
        "labels": [DECISION_LABELS[o] for o in outcome_order],
        "counts": [outcome_counts[o] for o in outcome_order],
        "colors": [DECISION_COLORS[o] for o in outcome_order],
    }

    # --- Assessment Pipeline (horizontal bar) ---
    status_order = [
        ASSESSMENT_STATUS_DRAFT, ASSESSMENT_STATUS_SENT,
        ASSESSMENT_STATUS_IN_PROGRESS, ASSESSMENT_STATUS_SUBMITTED,
        ASSESSMENT_STATUS_REVIEWED,
    ]
    status_counts = {s: 0 for s in status_order}
    for a in all_assessments:
        if a.status in status_counts:
            status_counts[a.status] += 1

    assessment_pipeline = {
        "labels": [STATUS_LABELS[s] for s in status_order],
        "counts": [status_counts[s] for s in status_order],
        "colors": [STATUS_COLORS[s] for s in status_order],
    }

    # --- Category Analysis (horizontal bar, avg across all finalized) ---
    category_earned_total = {}
    category_possible_total = {}

    for scores in scores_by_vendor.values():
        for cat_data in scores.get("category_scores", []):
            cat = cat_data["category"]
            category_earned_total[cat] = (
                category_earned_total.get(cat, 0.0) + cat_data["earned"]
            )
            category_possible_total[cat] = (
                category_possible_total.get(cat, 0.0) + cat_data["possible"]
            )

    category_analysis_items = []
    for cat in category_earned_total:
        possible = category_possible_total[cat]
        if possible > 0:
            score = round((category_earned_total[cat] / possible) * 100, 1)
        else:
            score = 0.0
        category_analysis_items.append((cat, score))

    # Sort worst-first
    category_analysis_items.sort(key=lambda x: x[1])

    category_analysis = {
        "labels": [c[0] for c in category_analysis_items],
        "scores": [c[1] for c in category_analysis_items],
        "colors": [_score_color(c[1]) for c in category_analysis_items],
    }

    # --- Vendor Table ---
    vendor_rows = []
    for v in vendors:
        decision = latest_decision_by_vendor.get(v.id)
        scores = scores_by_vendor.get(v.id)
        overall_score = scores["overall_score"] if scores else None

        assessment_count = sum(1 for a in all_assessments if a.vendor_id == v.id)

        is_overdue = False
        next_review_date = None
        last_assessed_date = None

        if decision:
            if decision.next_review_date:
                next_review_date = decision.next_review_date.strftime("%Y-%m-%d")
                is_overdue = decision.next_review_date.date() < today
            if decision.finalized_at:
                last_assessed_date = decision.finalized_at.strftime("%Y-%m-%d")

        vendor_rows.append({
            "id": v.id,
            "name": v.name,
            "status": v.status,
            "risk_rating": decision.overall_risk_rating if decision else None,
            "risk_rating_display": (
                RISK_LABELS.get(decision.overall_risk_rating)
                if decision and decision.overall_risk_rating
                else None
            ),
            "decision_outcome": decision.decision_outcome if decision else None,
            "decision_outcome_display": (
                DECISION_LABELS.get(decision.decision_outcome)
                if decision and decision.decision_outcome
                else None
            ),
            "overall_score": overall_score,
            "last_assessed_date": last_assessed_date,
            "next_review_date": next_review_date,
            "is_overdue": is_overdue,
            "assessment_count": assessment_count,
        })

    return {
        "kpis": {
            "total_active_vendors": total_active_vendors,
            "average_risk_score": average_risk_score,
            "pending_assessments": pending_assessments,
            "overdue_reviews": overdue_reviews,
        },
        "risk_distribution": risk_distribution,
        "decision_outcomes": decision_outcomes,
        "assessment_pipeline": assessment_pipeline,
        "category_analysis": category_analysis,
        "vendors": vendor_rows,
    }
