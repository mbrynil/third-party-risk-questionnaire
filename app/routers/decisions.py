from datetime import datetime

from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
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
async def assessment_decision_page(request: Request, assessment_id: int, db: Session = Depends(get_db)):
    ctx = _load_decision_context(db, assessment_id)
    scores = ctx["scores"]

    return templates.TemplateResponse("assessment_decision.html", {
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
        "evidence_count": ctx["evidence_count"],
        "followup_total": ctx["followup_total"],
        "followup_open": ctx["followup_open"],
        "risk_levels": VALID_RISK_LEVELS,
        "decision_outcomes": VALID_DECISION_OUTCOMES,
        "risk_suggestions": ctx["risk_suggestions"],
    })


@router.get("/assessments/{assessment_id}/report", response_class=HTMLResponse)
async def assessment_report_page(request: Request, assessment_id: int, db: Session = Depends(get_db)):
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


@router.post("/assessments/{assessment_id}/decision/generate")
async def auto_generate_draft(assessment_id: int, db: Session = Depends(get_db)):
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
    db: Session = Depends(get_db)
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
        transition_to_reviewed(db, assessment)

    db.commit()

    if action == "finalize":
        return RedirectResponse(
            url=f"/vendors/{assessment.vendor_id}?message=Assessment finalized successfully&message_type=success",
            status_code=303
        )
    else:
        return RedirectResponse(
            url=f"/assessments/{assessment_id}/decision?message=Draft saved&message_type=success",
            status_code=303
        )
