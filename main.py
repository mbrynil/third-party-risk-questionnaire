from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import List, Optional
import uuid

from models import (
    init_db, get_db, seed_question_bank, 
    Questionnaire, Question, Response, Answer, QuestionBankItem, 
    VALID_CHOICES, RESPONSE_STATUS_DRAFT, RESPONSE_STATUS_SUBMITTED
)
from datetime import datetime

app = FastAPI(title="Third-Party Risk Questionnaire System")
templates = Jinja2Templates(directory="templates")

init_db()
seed_question_bank()


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("home.html", {"request": request})


@app.get("/create", response_class=HTMLResponse)
async def create_questionnaire_page(request: Request, db: Session = Depends(get_db)):
    question_bank = db.query(QuestionBankItem).filter(
        QuestionBankItem.is_active == True
    ).order_by(QuestionBankItem.category, QuestionBankItem.id).all()
    
    categories = {}
    for item in question_bank:
        if item.category not in categories:
            categories[item.category] = []
        categories[item.category].append(item)
    
    return templates.TemplateResponse("create.html", {
        "request": request,
        "categories": categories
    })


@app.post("/create")
async def create_questionnaire(
    request: Request,
    company_name: str = Form(...),
    title: str = Form(...),
    custom_questions: str = Form(""),
    db: Session = Depends(get_db)
):
    form_data = await request.form()
    question_ids = form_data.getlist("question_ids")
    
    if not question_ids and not custom_questions.strip():
        question_bank = db.query(QuestionBankItem).filter(
            QuestionBankItem.is_active == True
        ).order_by(QuestionBankItem.category, QuestionBankItem.id).all()
        categories = {}
        for item in question_bank:
            if item.category not in categories:
                categories[item.category] = []
            categories[item.category].append(item)
        return templates.TemplateResponse("create.html", {
            "request": request,
            "categories": categories,
            "error": "Please select at least one question from the bank or add custom questions."
        })
    
    token = str(uuid.uuid4())[:8]
    
    questionnaire = Questionnaire(company_name=company_name, title=title, token=token)
    db.add(questionnaire)
    db.flush()
    
    order = 0
    for qid in question_ids:
        bank_item = db.query(QuestionBankItem).filter(QuestionBankItem.id == int(str(qid))).first()
        if bank_item:
            question = Question(
                questionnaire_id=questionnaire.id,
                question_text=bank_item.text,
                order=order
            )
            db.add(question)
            order += 1
    
    if custom_questions.strip():
        custom_lines = [q.strip() for q in custom_questions.strip().split('\n') if q.strip()]
        for q_text in custom_lines:
            question = Question(
                questionnaire_id=questionnaire.id,
                question_text=q_text,
                order=order
            )
            db.add(question)
            order += 1
    
    db.commit()
    
    base_url = str(request.base_url).rstrip('/')
    vendor_url = f"{base_url}/vendor/{token}"
    
    return templates.TemplateResponse("created.html", {
        "request": request,
        "questionnaire": questionnaire,
        "token": token,
        "vendor_url": vendor_url
    })


@app.get("/vendor/{token}", response_class=HTMLResponse)
async def vendor_form(request: Request, token: str, email: Optional[str] = None, db: Session = Depends(get_db)):
    questionnaire = db.query(Questionnaire).filter(Questionnaire.token == token).first()
    if not questionnaire:
        raise HTTPException(status_code=404, detail="Questionnaire not found")
    
    questions = db.query(Question).filter(
        Question.questionnaire_id == questionnaire.id
    ).order_by(Question.order).all()
    
    existing_response = None
    if email:
        existing_response = db.query(Response).filter(
            Response.questionnaire_id == questionnaire.id,
            Response.vendor_email == email
        ).first()
    
    return templates.TemplateResponse("vendor_form.html", {
        "request": request,
        "questionnaire": questionnaire,
        "questions": questions,
        "existing_response": existing_response,
        "RESPONSE_STATUS_SUBMITTED": RESPONSE_STATUS_SUBMITTED
    })


@app.post("/vendor/{token}")
async def submit_vendor_response(
    request: Request,
    token: str,
    db: Session = Depends(get_db)
):
    questionnaire = db.query(Questionnaire).filter(Questionnaire.token == token).first()
    if not questionnaire:
        raise HTTPException(status_code=404, detail="Questionnaire not found")
    
    form_data = await request.form()
    vendor_name = str(form_data.get("vendor_name", "")).strip()
    vendor_email = str(form_data.get("vendor_email", "")).strip()
    action = str(form_data.get("action", "submit"))
    
    questions = db.query(Question).filter(
        Question.questionnaire_id == questionnaire.id
    ).order_by(Question.order).all()
    
    errors = []
    if not vendor_name:
        errors.append("Company name is required.")
    if not vendor_email:
        errors.append("Contact email is required.")
    
    existing_response = db.query(Response).filter(
        Response.questionnaire_id == questionnaire.id,
        Response.vendor_email == vendor_email
    ).first()
    
    if existing_response and existing_response.status == RESPONSE_STATUS_SUBMITTED:
        return templates.TemplateResponse("vendor_form.html", {
            "request": request,
            "questionnaire": questionnaire,
            "questions": questions,
            "existing_response": existing_response,
            "RESPONSE_STATUS_SUBMITTED": RESPONSE_STATUS_SUBMITTED,
            "error": "You have already submitted this questionnaire. Editing is no longer allowed."
        })
    
    if action == "submit":
        missing_answers = []
        for question in questions:
            choice_key = f"choice_{question.id}"
            choice_value = form_data.get(choice_key, "")
            if not choice_value or choice_value not in VALID_CHOICES:
                missing_answers.append(question)
        
        if missing_answers:
            errors.append(f"Please answer all questions before submitting. {len(missing_answers)} unanswered.")
    
    if errors:
        return templates.TemplateResponse("vendor_form.html", {
            "request": request,
            "questionnaire": questionnaire,
            "questions": questions,
            "error": " ".join(errors),
            "form_data": dict(form_data),
            "RESPONSE_STATUS_SUBMITTED": RESPONSE_STATUS_SUBMITTED
        })
    
    if existing_response:
        response = existing_response
        response.vendor_name = vendor_name
        response.last_saved_at = datetime.utcnow()
        if action == "submit":
            response.status = RESPONSE_STATUS_SUBMITTED
            response.submitted_at = datetime.utcnow()
        db.query(Answer).filter(Answer.response_id == response.id).delete()
    else:
        response = Response(
            questionnaire_id=questionnaire.id,
            vendor_name=vendor_name,
            vendor_email=vendor_email,
            status=RESPONSE_STATUS_SUBMITTED if action == "submit" else RESPONSE_STATUS_DRAFT
        )
        db.add(response)
        db.flush()
    
    for question in questions:
        choice_key = f"choice_{question.id}"
        notes_key = f"notes_{question.id}"
        choice_value = form_data.get(choice_key, "") or None
        notes_value = str(form_data.get(notes_key, "")).strip() or None
        
        answer = Answer(
            response_id=response.id,
            question_id=question.id,
            answer_choice=choice_value if choice_value in VALID_CHOICES else None,
            notes=notes_value
        )
        db.add(answer)
    
    db.commit()
    
    if action == "submit":
        return templates.TemplateResponse("submitted.html", {"request": request})
    else:
        db.refresh(response)
        return templates.TemplateResponse("vendor_form.html", {
            "request": request,
            "questionnaire": questionnaire,
            "questions": questions,
            "existing_response": response,
            "RESPONSE_STATUS_SUBMITTED": RESPONSE_STATUS_SUBMITTED,
            "success": f"Draft saved at {response.last_saved_at.strftime('%Y-%m-%d %H:%M:%S')} UTC"
        })


@app.get("/api/vendor/{token}/check-draft")
async def check_draft(token: str, email: str, db: Session = Depends(get_db)):
    questionnaire = db.query(Questionnaire).filter(Questionnaire.token == token).first()
    if not questionnaire:
        raise HTTPException(status_code=404, detail="Questionnaire not found")
    
    response = db.query(Response).filter(
        Response.questionnaire_id == questionnaire.id,
        Response.vendor_email == email
    ).first()
    
    if not response:
        return {"found": False}
    
    answers_dict = {}
    for answer in response.answers:
        answers_dict[str(answer.question_id)] = {
            "choice": answer.answer_choice,
            "notes": answer.notes or ""
        }
    
    return {
        "found": True,
        "status": response.status,
        "vendor_name": response.vendor_name,
        "last_saved_at": response.last_saved_at.strftime('%Y-%m-%d %H:%M:%S') if response.last_saved_at else None,
        "answers": answers_dict
    }


@app.get("/responses", response_class=HTMLResponse)
async def view_responses(request: Request, status_filter: Optional[str] = None, db: Session = Depends(get_db)):
    questionnaires = db.query(Questionnaire).all()
    return templates.TemplateResponse("responses.html", {
        "request": request,
        "questionnaires": questionnaires,
        "status_filter": status_filter,
        "RESPONSE_STATUS_DRAFT": RESPONSE_STATUS_DRAFT,
        "RESPONSE_STATUS_SUBMITTED": RESPONSE_STATUS_SUBMITTED
    })


@app.get("/responses/{questionnaire_id}", response_class=HTMLResponse)
async def view_questionnaire_responses(
    request: Request,
    questionnaire_id: int,
    status_filter: Optional[str] = None,
    db: Session = Depends(get_db)
):
    questionnaire = db.query(Questionnaire).filter(Questionnaire.id == questionnaire_id).first()
    if not questionnaire:
        raise HTTPException(status_code=404, detail="Questionnaire not found")
    
    query = db.query(Response).filter(Response.questionnaire_id == questionnaire_id)
    if status_filter and status_filter in [RESPONSE_STATUS_DRAFT, RESPONSE_STATUS_SUBMITTED]:
        query = query.filter(Response.status == status_filter)
    responses = query.order_by(Response.last_saved_at.desc()).all()
    
    questions = db.query(Question).filter(
        Question.questionnaire_id == questionnaire_id
    ).order_by(Question.order).all()
    
    return templates.TemplateResponse("questionnaire_responses.html", {
        "request": request,
        "questionnaire": questionnaire,
        "responses": responses,
        "questions": questions,
        "status_filter": status_filter,
        "RESPONSE_STATUS_DRAFT": RESPONSE_STATUS_DRAFT,
        "RESPONSE_STATUS_SUBMITTED": RESPONSE_STATUS_SUBMITTED
    })


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)
