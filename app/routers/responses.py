from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime

from app import templates
from models import (
    get_db, Assessment, Question, Response, EvidenceFile, FollowUp,
    RESPONSE_STATUS_DRAFT, RESPONSE_STATUS_SUBMITTED, RESPONSE_STATUS_NEEDS_INFO,
    ASSESSMENT_STATUS_DRAFT, ASSESSMENT_STATUS_SENT, ASSESSMENT_STATUS_IN_PROGRESS,
    ASSESSMENT_STATUS_SUBMITTED, ASSESSMENT_STATUS_REVIEWED,
)
from app.services.evaluation import compute_response_evaluations

router = APIRouter()


@router.get("/responses", response_class=HTMLResponse)
async def view_responses(request: Request, status_filter: Optional[str] = None, db: Session = Depends(get_db)):
    assessments = db.query(Assessment).all()
    return templates.TemplateResponse("responses.html", {
        "request": request,
        "assessments": assessments,
        "status_filter": status_filter,
        "RESPONSE_STATUS_DRAFT": RESPONSE_STATUS_DRAFT,
        "RESPONSE_STATUS_SUBMITTED": RESPONSE_STATUS_SUBMITTED,
        "RESPONSE_STATUS_NEEDS_INFO": RESPONSE_STATUS_NEEDS_INFO
    })


@router.get("/responses/{assessment_id}", response_class=HTMLResponse)
async def view_assessment_responses(
    request: Request,
    assessment_id: int,
    status_filter: Optional[str] = None,
    db: Session = Depends(get_db)
):
    assessment = db.query(Assessment).filter(Assessment.id == assessment_id).first()
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")

    query = db.query(Response).filter(Response.assessment_id == assessment_id)
    if status_filter and status_filter in [RESPONSE_STATUS_DRAFT, RESPONSE_STATUS_SUBMITTED, RESPONSE_STATUS_NEEDS_INFO]:
        query = query.filter(Response.status == status_filter)
    responses = query.order_by(Response.last_saved_at.desc()).all()

    questions = db.query(Question).filter(
        Question.assessment_id == assessment_id
    ).order_by(Question.order).all()

    eval_dicts = {}
    for resp in responses:
        eval_dicts[resp.id] = compute_response_evaluations(questions, resp)

    return templates.TemplateResponse("questionnaire_responses.html", {
        "request": request,
        "assessment": assessment,
        "responses": responses,
        "questions": questions,
        "status_filter": status_filter,
        "eval_dicts": eval_dicts,
        "RESPONSE_STATUS_DRAFT": RESPONSE_STATUS_DRAFT,
        "RESPONSE_STATUS_SUBMITTED": RESPONSE_STATUS_SUBMITTED,
        "RESPONSE_STATUS_NEEDS_INFO": RESPONSE_STATUS_NEEDS_INFO,
        "ASSESSMENT_STATUS_DRAFT": ASSESSMENT_STATUS_DRAFT,
        "ASSESSMENT_STATUS_SENT": ASSESSMENT_STATUS_SENT,
        "ASSESSMENT_STATUS_IN_PROGRESS": ASSESSMENT_STATUS_IN_PROGRESS,
        "ASSESSMENT_STATUS_SUBMITTED": ASSESSMENT_STATUS_SUBMITTED,
        "ASSESSMENT_STATUS_REVIEWED": ASSESSMENT_STATUS_REVIEWED
    })


@router.post("/responses/{assessment_id}/followup/{response_id}")
async def create_followup(
    assessment_id: int,
    response_id: int,
    message: str = Form(...),
    db: Session = Depends(get_db)
):
    assessment = db.query(Assessment).filter(Assessment.id == assessment_id).first()
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")

    response = db.query(Response).filter(
        Response.id == response_id,
        Response.assessment_id == assessment_id
    ).first()
    if not response:
        raise HTTPException(status_code=404, detail="Response not found")

    followup = FollowUp(
        response_id=response_id,
        message=message.strip()
    )
    db.add(followup)

    response.status = RESPONSE_STATUS_NEEDS_INFO

    db.commit()

    return RedirectResponse(
        url=f"/responses/{assessment_id}#response-{response_id}",
        status_code=303
    )


@router.get("/submissions/{submission_id}/export", response_class=HTMLResponse)
async def export_submission(request: Request, submission_id: int, db: Session = Depends(get_db)):
    response = db.query(Response).filter(Response.id == submission_id).first()
    if not response:
        raise HTTPException(status_code=404, detail="Submission not found")

    assessment = db.query(Assessment).filter(Assessment.id == response.assessment_id).first()

    questions = db.query(Question).filter(
        Question.assessment_id == assessment.id
    ).order_by(Question.order).all()

    answers_dict = {}
    for answer in response.answers:
        answers_dict[answer.question_id] = answer

    eval_dict = compute_response_evaluations(questions, response)

    answered_count = sum(1 for a in response.answers if a.answer_choice)
    total_questions = len(questions)
    completion_percent = (answered_count / total_questions * 100) if total_questions > 0 else 0

    evidence_files = db.query(EvidenceFile).filter(
        EvidenceFile.response_id == response.id
    ).order_by(EvidenceFile.uploaded_at.desc()).all()

    follow_ups = db.query(FollowUp).filter(
        FollowUp.response_id == response.id
    ).order_by(FollowUp.created_at.desc()).all()

    return templates.TemplateResponse("export.html", {
        "request": request,
        "response": response,
        "assessment": assessment,
        "questions": questions,
        "answers_dict": answers_dict,
        "eval_dict": eval_dict,
        "completion_percent": completion_percent,
        "answered_count": answered_count,
        "evidence_files": evidence_files,
        "follow_ups": follow_ups,
        "RESPONSE_STATUS_DRAFT": RESPONSE_STATUS_DRAFT,
        "RESPONSE_STATUS_SUBMITTED": RESPONSE_STATUS_SUBMITTED,
        "RESPONSE_STATUS_NEEDS_INFO": RESPONSE_STATUS_NEEDS_INFO,
        "now": datetime.utcnow()
    })
