from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
import json

from app import templates
from models import (
    get_db, Assessment, Question, QuestionBankItem, ConditionalRule,
)
from app.services.lifecycle import transition_to_sent, transition_to_reviewed

router = APIRouter()


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

    return templates.TemplateResponse("edit.html", {
        "request": request,
        "assessment": assessment,
        "questions": questions,
        "rules": rules,
        "categories": categories
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
            valid_expected = [v for v in expected_list if v in ["yes", "no", "partial", "na"]]
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

    return templates.TemplateResponse("created.html", {
        "request": request,
        "assessment": assessment,
        "token": assessment.token,
        "vendor_url": vendor_url
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
                        question_bank_item_id=bank_item.id
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
