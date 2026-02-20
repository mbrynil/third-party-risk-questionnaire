from datetime import datetime

from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, Response as FastAPIResponse
from sqlalchemy.orm import Session

from app import templates
from models import (
    get_db, Assessment, Question, Response, Vendor, AssessmentDecision,
    RESPONSE_STATUS_SUBMITTED,
    DECISION_STATUS_FINAL,
    VALID_RISK_LEVELS, VALID_DECISION_OUTCOMES,
)
from app.services.decision_service import get_or_create_decision, save_decision
from app.services.scoring import compute_assessment_scores
from app.services.risk_statements import match_risk_statements
from app.services.lifecycle import transition_to_reviewed
from app.services.draft_generator import generate_draft
from app.services.remediation_service import auto_generate_remediations
from app.services.reassessment_service import suggest_next_review_date, compute_assessment_delta
from app.services.tiering import get_effective_tier
from app.services.activity_service import log_activity
from app.services.export_service import generate_assessment_report_pdf
from app.services.auth_service import require_login, require_role
from app.services.notification_service import create_notification
from models import ACTIVITY_DECISION_FINALIZED, NOTIF_DECISION_FINALIZED, RiskSnapshot, User

router = APIRouter()


def _load_decision_context(db: Session, assessment_id: int):
    """Load all shared data needed by the decision page and report page."""
    assessment = db.query(Assessment).filter(Assessment.id == assessment_id).first()
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")

    if not assessment.vendor_id:
        raise HTTPException(status_code=400, detail="Assessment has no linked vendor")

    vendor = db.query(Vendor).filter(Vendor.id == assessment.vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    decision = get_or_create_decision(db, assessment_id, vendor.id)

    response = db.query(Response).filter(
        Response.assessment_id == assessment_id,
        Response.status == RESPONSE_STATUS_SUBMITTED
    ).first()

    questions = db.query(Question).filter(
        Question.assessment_id == assessment_id
    ).order_by(Question.order).all()

    scores = compute_assessment_scores(questions, response)
    risk_suggestions = match_risk_statements(db, scores)

    evidence_files = response.evidence_files if response else []
    follow_ups = response.follow_ups if response else []
    evidence_count = len(evidence_files)
    followup_total = len(follow_ups)
    followup_open = sum(1 for f in follow_ups if not f.response_text)

    return {
        "assessment": assessment,
        "vendor": vendor,
        "decision": decision,
        "response": response,
        "questions": questions,
        "scores": scores,
        "risk_suggestions": risk_suggestions,
        "evidence_files": evidence_files,
        "follow_ups": follow_ups,
        "evidence_count": evidence_count,
        "followup_total": followup_total,
        "followup_open": followup_open,
    }


@router.get("/assessments/{assessment_id}/decision", response_class=HTMLResponse)
async def assessment_decision_page(request: Request, assessment_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_login)):
    ctx = _load_decision_context(db, assessment_id)
    scores = ctx["scores"]
    assessment = ctx["assessment"]
    vendor = ctx["vendor"]

    # Auto-suggest next review date based on vendor tier
    effective_tier = get_effective_tier(vendor)
    suggested_review_date = None
    if effective_tier:
        # Use now as placeholder for suggestion (actual finalized_at may not exist yet)
        suggested_review_date = suggest_next_review_date(effective_tier, datetime.utcnow())

    # Delta comparison for reassessments
    delta = None
    if assessment.previous_assessment_id:
        prev_assessment = db.query(Assessment).filter(
            Assessment.id == assessment.previous_assessment_id
        ).first()
        if prev_assessment:
            prev_questions = db.query(Question).filter(
                Question.assessment_id == prev_assessment.id
            ).order_by(Question.order).all()
            prev_response = db.query(Response).filter(
                Response.assessment_id == prev_assessment.id,
                Response.status == RESPONSE_STATUS_SUBMITTED
            ).order_by(Response.submitted_at.desc()).first()

            if prev_questions and prev_response:
                prev_scores = compute_assessment_scores(prev_questions, prev_response)
                delta = compute_assessment_delta(scores, prev_scores)

    return templates.TemplateResponse("assessment_decision.html", {
        "request": request,
        "assessment": assessment,
        "vendor": vendor,
        "decision": ctx["decision"],
        "response": ctx["response"],
        "total_questions": len(ctx["questions"]),
        "scores": scores,
        **{k: scores[k] for k in ("meets_count", "partial_count", "does_not_meet_count", "no_expectation_count")},
        "evidence_files": ctx["evidence_files"],
        "follow_ups": ctx["follow_ups"],
        "evidence_count": ctx["evidence_count"],
        "followup_total": ctx["followup_total"],
        "followup_open": ctx["followup_open"],
        "risk_levels": VALID_RISK_LEVELS,
        "decision_outcomes": VALID_DECISION_OUTCOMES,
        "risk_suggestions": ctx["risk_suggestions"],
        "effective_tier": effective_tier,
        "suggested_review_date": suggested_review_date.strftime("%Y-%m-%d") if suggested_review_date else None,
        "delta": delta,
    })


@router.get("/assessments/{assessment_id}/report", response_class=HTMLResponse)
async def assessment_report_page(request: Request, assessment_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_login)):
    ctx = _load_decision_context(db, assessment_id)

    if ctx["decision"].status != DECISION_STATUS_FINAL:
        return RedirectResponse(
            url=f"/assessments/{assessment_id}/decision?message=Report is only available for finalized assessments&message_type=warning",
            status_code=303
        )

    scores = ctx["scores"]

    return templates.TemplateResponse("assessment_report.html", {
        "request": request,
        "assessment": ctx["assessment"],
        "vendor": ctx["vendor"],
        "decision": ctx["decision"],
        "response": ctx["response"],
        "total_questions": len(ctx["questions"]),
        "scores": scores,
        **{k: scores[k] for k in ("meets_count", "partial_count", "does_not_meet_count", "no_expectation_count")},
        "evidence_files": ctx["evidence_files"],
        "follow_ups": ctx["follow_ups"],
        "now": datetime.utcnow(),
    })


@router.get("/assessments/{assessment_id}/report.pdf")
async def assessment_report_pdf(assessment_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_login)):
    ctx = _load_decision_context(db, assessment_id)

    if ctx["decision"].status != DECISION_STATUS_FINAL:
        raise HTTPException(status_code=400, detail="Report is only available for finalized assessments")

    scores = ctx["scores"]
    template_ctx = {
        "assessment": ctx["assessment"],
        "vendor": ctx["vendor"],
        "decision": ctx["decision"],
        "response": ctx["response"],
        "total_questions": len(ctx["questions"]),
        "scores": scores,
        **{k: scores[k] for k in ("meets_count", "partial_count", "does_not_meet_count", "no_expectation_count")},
        "evidence_files": ctx["evidence_files"],
        "follow_ups": ctx["follow_ups"],
        "now": datetime.utcnow(),
    }
    try:
        pdf_bytes = generate_assessment_report_pdf(template_ctx)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    vendor_name = ctx["vendor"].name.replace(" ", "_")
    filename = f"assessment_report_{vendor_name}_{assessment_id}.pdf"
    return FastAPIResponse(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/assessments/{assessment_id}/decision/generate")
async def auto_generate_draft(assessment_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_role("admin", "analyst"))):
    ctx = _load_decision_context(db, assessment_id)
    decision = ctx["decision"]

    if decision.status == DECISION_STATUS_FINAL:
        return RedirectResponse(
            url=f"/assessments/{assessment_id}/decision?message=Cannot generate draft — assessment already finalized&message_type=warning",
            status_code=303
        )

    generated = generate_draft(ctx["scores"], ctx["risk_suggestions"])

    save_decision(
        db, decision, "draft",
        overall_risk_rating=generated["overall_risk_rating"],
        decision_outcome=generated["decision_outcome"],
        key_findings=generated["key_findings"],
        remediation_required=generated["remediation_required"],
        rationale=generated["rationale"],
    )
    db.commit()

    return RedirectResponse(
        url=f"/assessments/{assessment_id}/decision?message=Draft auto-generated. Review and edit before finalizing.&message_type=success",
        status_code=303
    )


@router.post("/assessments/{assessment_id}/decision", response_class=HTMLResponse)
async def save_assessment_decision(
    request: Request,
    assessment_id: int,
    action: str = Form(...),
    data_sensitivity: str = Form(None),
    business_criticality: str = Form(None),
    impact_rating: str = Form(None),
    likelihood_rating: str = Form(None),
    overall_risk_rating: str = Form(None),
    decision_outcome: str = Form(None),
    rationale: str = Form(None),
    key_findings: str = Form(None),
    remediation_required: str = Form(None),
    next_review_date: str = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "analyst")),
):
    assessment = db.query(Assessment).filter(Assessment.id == assessment_id).first()
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")

    decision = db.query(AssessmentDecision).filter(
        AssessmentDecision.assessment_id == assessment_id
    ).first()

    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")

    if decision.status == DECISION_STATUS_FINAL:
        return RedirectResponse(
            url=f"/vendors/{assessment.vendor_id}?message=Assessment already finalized&message_type=warning",
            status_code=303
        )

    success, error_msg = save_decision(
        db, decision, action,
        data_sensitivity=data_sensitivity,
        business_criticality=business_criticality,
        impact_rating=impact_rating,
        likelihood_rating=likelihood_rating,
        overall_risk_rating=overall_risk_rating,
        decision_outcome=decision_outcome,
        rationale=rationale,
        key_findings=key_findings,
        remediation_required=remediation_required,
        next_review_date=next_review_date,
    )

    if not success and error_msg:
        return RedirectResponse(
            url=f"/assessments/{assessment_id}/decision?message={error_msg}&message_type=danger",
            status_code=303
        )

    if action == "finalize" and success:
        decision.decided_by_id = current_user.id
        transition_to_reviewed(db, assessment)
        if assessment.vendor_id:
            outcome_label = (decision_outcome or "").replace("_", " ").title()
            log_activity(db, assessment.vendor_id, ACTIVITY_DECISION_FINALIZED,
                         f"Decision finalized for '{assessment.title}': {outcome_label}",
                         assessment_id=assessment.id, user_id=current_user.id)

        # Persist overall_score on the decision
        ctx = _load_decision_context(db, assessment_id)
        scores = ctx["scores"]
        if scores.get("overall_score") is not None:
            decision.overall_score = int(scores["overall_score"])

        # Auto-generate remediation items from risk statements
        risk_suggestions = ctx["risk_suggestions"]
        remediation_data = []
        for rs in risk_suggestions:
            remediation_data.append({
                "risk_statement_id": rs.get("id"),
                "severity": rs.get("severity", "MEDIUM"),
                "category": rs.get("category", ""),
                "finding": rs.get("finding_text", ""),
                "remediation": rs.get("remediation_text", ""),
            })
        rem_count = auto_generate_remediations(db, decision, remediation_data)

        # Create notification for decision finalization
        create_notification(
            db, NOTIF_DECISION_FINALIZED,
            f"Decision finalized for {assessment.company_name}: {(decision_outcome or '').replace('_', ' ').title()}",
            link=f"/assessments/{assessment_id}/decision",
            vendor_id=assessment.vendor_id,
            assessment_id=assessment_id,
        )

        # Record risk snapshot for historical trends
        db.add(RiskSnapshot(
            vendor_id=assessment.vendor_id,
            assessment_id=assessment_id,
            decision_id=decision.id,
            overall_score=decision.overall_score,
            risk_rating=decision.overall_risk_rating,
            decision_outcome=decision.decision_outcome,
        ))

    db.commit()

    if action == "finalize":
        msg = "Assessment finalized successfully"
        if rem_count > 0:
            msg += f" — {rem_count} remediation items created"
        return RedirectResponse(
            url=f"/vendors/{assessment.vendor_id}?message={msg}&message_type=success",
            status_code=303
        )
    else:
        return RedirectResponse(
            url=f"/assessments/{assessment_id}/decision?message=Draft saved&message_type=success",
            status_code=303
        )
