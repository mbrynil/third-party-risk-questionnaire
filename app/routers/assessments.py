from datetime import datetime, timedelta

from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session
import json

from app import templates
import json as json_lib

from sqlalchemy import func

from models import (
    get_db, Assessment, Question, QuestionBankItem, ConditionalRule,
    VendorContact, ReminderLog, AssessmentDecision,
    REMINDER_TYPE_REMINDER,
    get_answer_options, has_custom_answer_options,
)
from app.services.lifecycle import transition_to_sent, transition_to_reviewed
from app.services.email_service import send_assessment_invitation
from app.services.activity_service import log_activity
from app.services.export_service import generate_assessment_tracker_csv
from models import ACTIVITY_ASSESSMENT_SENT

router = APIRouter()


@router.get("/assessments/tracker", response_class=HTMLResponse)
async def assessment_tracker(request: Request, db: Session = Depends(get_db)):
    """Assessment pipeline tracker — shows all assessments with status, reminders, and actions."""
    now = datetime.utcnow()

    assessments = db.query(Assessment).order_by(Assessment.created_at.desc()).all()

    # Get reminder counts per assessment
    assessment_ids = [a.id for a in assessments]
    reminder_counts = {}
    if assessment_ids:
        counts = db.query(
            ReminderLog.assessment_id, func.count(ReminderLog.id)
        ).filter(
            ReminderLog.assessment_id.in_(assessment_ids),
            ReminderLog.reminder_type == REMINDER_TYPE_REMINDER,
        ).group_by(ReminderLog.assessment_id).all()
        reminder_counts = {aid: cnt for aid, cnt in counts}

    # Get decisions
    decisions_list = db.query(AssessmentDecision).filter(
        AssessmentDecision.assessment_id.in_(assessment_ids)
    ).all() if assessment_ids else []
    decisions = {d.assessment_id: d for d in decisions_list}

    # Build enriched rows
    rows = []
    for a in assessments:
        days_waiting = None
        if a.sent_at and a.status in ("SENT", "IN_PROGRESS"):
            days_waiting = (now - a.sent_at).days

        decision = decisions.get(a.id)

        rows.append({
            "assessment": a,
            "vendor_name": a.vendor.name if a.vendor else a.company_name,
            "vendor_id": a.vendor_id,
            "days_waiting": days_waiting,
            "reminder_count": reminder_counts.get(a.id, 0),
            "decision": decision,
        })

    return templates.TemplateResponse("assessment_tracker.html", {
        "request": request,
        "rows": rows,
        "now": now,
    })


@router.get("/assessments/tracker.csv")
async def assessment_tracker_csv(db: Session = Depends(get_db)):
    csv_content = generate_assessment_tracker_csv(db)
    filename = f"assessment_tracker_{datetime.utcnow().strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/questionnaire/{assessment_id}/edit", response_class=HTMLResponse)
async def edit_assessment_page(request: Request, assessment_id: int, db: Session = Depends(get_db)):
    assessment = db.query(Assessment).filter(
        Assessment.id == assessment_id
    ).first()
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")

    questions = db.query(Question).filter(
        Question.assessment_id == assessment.id
    ).order_by(Question.order).all()

    rules = db.query(ConditionalRule).filter(
        ConditionalRule.assessment_id == assessment.id
    ).all()

    question_bank = db.query(QuestionBankItem).filter(
        QuestionBankItem.is_active == True
    ).order_by(QuestionBankItem.category, QuestionBankItem.id).all()

    categories = {}
    for item in question_bank:
        if item.category not in categories:
            categories[item.category] = []
        categories[item.category].append(item)

    question_options = {str(q.id): get_answer_options(q) for q in questions}

    return templates.TemplateResponse("edit.html", {
        "request": request,
        "assessment": assessment,
        "questions": questions,
        "rules": rules,
        "categories": categories,
        "question_options_json": json_lib.dumps(question_options),
    })


@router.post("/questionnaire/{assessment_id}/edit")
async def update_assessment(
    request: Request,
    assessment_id: int,
    company_name: str = Form(...),
    title: str = Form(...),
    db: Session = Depends(get_db)
):
    assessment = db.query(Assessment).filter(
        Assessment.id == assessment_id
    ).first()
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")

    form_data = await request.form()

    assessment.company_name = company_name.strip()
    assessment.title = title.strip()

    questions = db.query(Question).filter(
        Question.assessment_id == assessment.id
    ).all()

    for q in questions:
        weight = form_data.get(f"weight_{q.id}", q.weight)
        if weight in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]:
            q.weight = weight

        answer_mode = form_data.get(f"answer_mode_{q.id}", q.answer_mode)
        if answer_mode in ["SINGLE", "MULTI"]:
            q.answer_mode = answer_mode

        expected_list = form_data.getlist(f"expected_{q.id}[]")
        if expected_list:
            valid_opts = get_answer_options(q)
            valid_expected = [v for v in expected_list if v in valid_opts]
            if valid_expected:
                q.expected_values = json.dumps(valid_expected)
                q.expected_value = valid_expected[0]
            else:
                q.expected_values = None
                q.expected_value = None
        else:
            q.expected_values = None
            q.expected_value = None

    db.commit()

    return RedirectResponse(url=f"/questionnaire/{assessment_id}/edit?saved=1", status_code=303)


@router.get("/questionnaire/{assessment_id}/share", response_class=HTMLResponse)
async def share_assessment(request: Request, assessment_id: int, db: Session = Depends(get_db)):
    assessment = db.query(Assessment).filter(
        Assessment.id == assessment_id
    ).first()
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")

    transition_to_sent(db, assessment)

    base_url = str(request.base_url).rstrip('/')
    vendor_url = f"{base_url}/vendor/{assessment.token}"

    contacts = []
    if assessment.vendor_id:
        contacts = db.query(VendorContact).filter(
            VendorContact.vendor_id == assessment.vendor_id,
            VendorContact.email.isnot(None),
            VendorContact.email != "",
        ).order_by(VendorContact.name).all()

    return templates.TemplateResponse("created.html", {
        "request": request,
        "assessment": assessment,
        "token": assessment.token,
        "vendor_url": vendor_url,
        "contacts": contacts,
    })


@router.post("/questionnaire/{assessment_id}/add-questions")
async def add_questions_to_assessment(
    request: Request,
    assessment_id: int,
    bank_ids: str = Form(""),
    custom_text: str = Form(""),
    db: Session = Depends(get_db)
):
    assessment = db.query(Assessment).filter(
        Assessment.id == assessment_id
    ).first()
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")

    max_order = db.query(Question).filter(
        Question.assessment_id == assessment.id
    ).count()

    order = max_order

    if bank_ids.strip():
        for qid in bank_ids.split(','):
            qid = qid.strip()
            if qid:
                bank_item = db.query(QuestionBankItem).filter(QuestionBankItem.id == int(qid)).first()
                if bank_item:
                    question = Question(
                        assessment_id=assessment.id,
                        question_text=bank_item.text,
                        order=order,
                        weight="MEDIUM",
                        expected_operator="EQUALS",
                        expected_value=None,
                        expected_values=None,
                        expected_value_type="CHOICE",
                        answer_mode="SINGLE",
                        category=bank_item.category,
                        question_bank_item_id=bank_item.id,
                        answer_options=bank_item.answer_options,
                    )
                    db.add(question)
                    order += 1

    if custom_text.strip():
        question = Question(
            assessment_id=assessment.id,
            question_text=custom_text.strip(),
            order=order,
            weight="MEDIUM",
            expected_operator="EQUALS",
            expected_value=None,
            expected_values=None,
            expected_value_type="CHOICE",
            answer_mode="SINGLE"
        )
        db.add(question)

    db.commit()

    return RedirectResponse(url=f"/questionnaire/{assessment_id}/edit", status_code=303)


@router.post("/questionnaire/{assessment_id}/remove-question")
async def remove_question_from_assessment(
    assessment_id: int,
    question_id: int = Form(...),
    db: Session = Depends(get_db)
):
    question = db.query(Question).filter(
        Question.id == question_id,
        Question.assessment_id == assessment_id
    ).first()
    if question:
        db.query(ConditionalRule).filter(
            (ConditionalRule.trigger_question_id == question_id) |
            (ConditionalRule.target_question_id == question_id)
        ).delete()
        db.delete(question)
        db.commit()

    return RedirectResponse(url=f"/questionnaire/{assessment_id}/edit", status_code=303)


@router.post("/questionnaire/{assessment_id}/add-rule")
async def add_rule_to_assessment(
    assessment_id: int,
    trigger_id: int = Form(...),
    target_id: int = Form(...),
    trigger_values: str = Form(...),
    make_required: str = Form("0"),
    db: Session = Depends(get_db)
):
    assessment = db.query(Assessment).filter(
        Assessment.id == assessment_id
    ).first()
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")

    rule = ConditionalRule(
        assessment_id=assessment.id,
        trigger_question_id=trigger_id,
        operator="IN",
        trigger_values=trigger_values,
        target_question_id=target_id,
        make_required=(make_required == "1")
    )
    db.add(rule)
    db.commit()

    return RedirectResponse(url=f"/questionnaire/{assessment_id}/edit", status_code=303)


@router.post("/questionnaire/{assessment_id}/delete-rule")
async def delete_rule_from_assessment(
    assessment_id: int,
    rule_id: int = Form(...),
    db: Session = Depends(get_db)
):
    rule = db.query(ConditionalRule).filter(
        ConditionalRule.id == rule_id,
        ConditionalRule.assessment_id == assessment_id
    ).first()
    if rule:
        db.delete(rule)
        db.commit()

    return RedirectResponse(url=f"/questionnaire/{assessment_id}/edit", status_code=303)


@router.post("/questionnaire/{assessment_id}/mark-reviewed")
async def mark_assessment_reviewed(
    assessment_id: int,
    db: Session = Depends(get_db)
):
    assessment = db.query(Assessment).filter(
        Assessment.id == assessment_id
    ).first()
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")

    if transition_to_reviewed(db, assessment):
        db.commit()

    return RedirectResponse(url=f"/responses/{assessment_id}?marked_reviewed=1", status_code=303)


@router.post("/assessments/{assessment_id}/send")
async def send_assessment_email(
    request: Request,
    assessment_id: int,
    contact_email: str = Form(...),
    contact_name: str = Form(""),
    custom_message: str = Form(""),
    expiry_days: int = Form(30),
    db: Session = Depends(get_db),
):
    assessment = db.query(Assessment).filter(
        Assessment.id == assessment_id
    ).first()
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")

    base_url = str(request.base_url).rstrip("/")
    assessment_url = f"{base_url}/vendor/{assessment.token}"

    expires_at = datetime.utcnow() + timedelta(days=expiry_days) if expiry_days > 0 else None

    result = send_assessment_invitation(
        to_email=contact_email.strip(),
        to_name=contact_name.strip() or assessment.company_name,
        vendor_name=assessment.company_name,
        assessment_title=assessment.title,
        assessment_url=assessment_url,
        custom_message=custom_message.strip() or None,
        expires_at=expires_at,
    )

    # Update assessment record
    assessment.sent_to_email = contact_email.strip()
    assessment.sent_at = datetime.utcnow()
    if expires_at:
        assessment.expires_at = expires_at
    transition_to_sent(db, assessment)
    if assessment.vendor_id:
        log_activity(db, assessment.vendor_id, ACTIVITY_ASSESSMENT_SENT,
                     f"Assessment '{assessment.title}' sent to {contact_email.strip()}",
                     assessment_id=assessment.id)
    db.commit()

    # Redirect back to referrer or vendor profile
    referer = request.headers.get("referer", "")
    if "/vendors/" in referer:
        vendor_url = referer.split("?")[0]
        return RedirectResponse(url=f"{vendor_url}?email_sent=1", status_code=303)
    elif "/templates" in referer:
        return RedirectResponse(url=f"/templates?email_sent=1", status_code=303)
    else:
        return RedirectResponse(
            url=f"/questionnaire/{assessment_id}/share?email_sent=1",
            status_code=303,
        )


@router.post("/assessments/{assessment_id}/toggle-reminders")
async def toggle_assessment_reminders(
    request: Request,
    assessment_id: int,
    db: Session = Depends(get_db),
):
    """Pause or resume automated reminders for an assessment."""
    assessment = db.query(Assessment).filter(
        Assessment.id == assessment_id
    ).first()
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")

    assessment.reminders_paused = not assessment.reminders_paused
    db.commit()

    referer = request.headers.get("referer", "/")
    return RedirectResponse(url=referer, status_code=303)


@router.get("/email-log", response_class=HTMLResponse)
async def view_email_log(request: Request):
    """Development tool: view all emails sent via console provider."""
    import os
    log_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "email_log.json",
    )
    entries = []
    if os.path.exists(log_path):
        try:
            with open(log_path, "r") as f:
                entries = json.loads(f.read())
            entries.reverse()  # newest first
        except (json.JSONDecodeError, IOError):
            pass

    return templates.TemplateResponse("email_log.html", {
        "request": request,
        "entries": entries,
    })
