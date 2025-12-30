from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import List, Optional
import uuid

from models import init_db, get_db, seed_question_bank, Questionnaire, Question, Response, Answer, QuestionBankItem

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
    
    questionnaire = Questionnaire(title=title, token=token)
    db.add(questionnaire)
    db.flush()
    
    order = 0
    for qid in question_ids:
        bank_item = db.query(QuestionBankItem).filter(QuestionBankItem.id == int(qid)).first()
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
    
    return templates.TemplateResponse("created.html", {
        "request": request,
        "questionnaire": questionnaire,
        "token": token
    })


@app.get("/vendor/{token}", response_class=HTMLResponse)
async def vendor_form(request: Request, token: str, db: Session = Depends(get_db)):
    questionnaire = db.query(Questionnaire).filter(Questionnaire.token == token).first()
    if not questionnaire:
        raise HTTPException(status_code=404, detail="Questionnaire not found")
    
    questions = db.query(Question).filter(
        Question.questionnaire_id == questionnaire.id
    ).order_by(Question.order).all()
    
    return templates.TemplateResponse("vendor_form.html", {
        "request": request,
        "questionnaire": questionnaire,
        "questions": questions
    })


@app.post("/vendor/{token}")
async def submit_vendor_response(
    request: Request,
    token: str,
    vendor_name: str = Form(...),
    vendor_email: str = Form(...),
    db: Session = Depends(get_db)
):
    questionnaire = db.query(Questionnaire).filter(Questionnaire.token == token).first()
    if not questionnaire:
        raise HTTPException(status_code=404, detail="Questionnaire not found")
    
    response = Response(
        questionnaire_id=questionnaire.id,
        vendor_name=vendor_name,
        vendor_email=vendor_email
    )
    db.add(response)
    db.flush()
    
    form_data = await request.form()
    questions = db.query(Question).filter(
        Question.questionnaire_id == questionnaire.id
    ).all()
    
    for question in questions:
        answer_key = f"answer_{question.id}"
        answer_text = form_data.get(answer_key, "")
        answer = Answer(
            response_id=response.id,
            question_id=question.id,
            answer_text=answer_text
        )
        db.add(answer)
    
    db.commit()
    
    return templates.TemplateResponse("submitted.html", {"request": request})


@app.get("/responses", response_class=HTMLResponse)
async def view_responses(request: Request, db: Session = Depends(get_db)):
    questionnaires = db.query(Questionnaire).all()
    return templates.TemplateResponse("responses.html", {
        "request": request,
        "questionnaires": questionnaires
    })


@app.get("/responses/{questionnaire_id}", response_class=HTMLResponse)
async def view_questionnaire_responses(
    request: Request,
    questionnaire_id: int,
    db: Session = Depends(get_db)
):
    questionnaire = db.query(Questionnaire).filter(Questionnaire.id == questionnaire_id).first()
    if not questionnaire:
        raise HTTPException(status_code=404, detail="Questionnaire not found")
    
    responses = db.query(Response).filter(
        Response.questionnaire_id == questionnaire_id
    ).order_by(Response.submitted_at.desc()).all()
    
    questions = db.query(Question).filter(
        Question.questionnaire_id == questionnaire_id
    ).order_by(Question.order).all()
    
    return templates.TemplateResponse("questionnaire_responses.html", {
        "request": request,
        "questionnaire": questionnaire,
        "responses": responses,
        "questions": questions
    })


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)
