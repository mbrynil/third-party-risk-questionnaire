from fastapi import FastAPI, Request, Form, Depends, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import List, Optional
import uuid
import os
import re

from models import (
    init_db, get_db, seed_question_bank, 
    Questionnaire, Question, Response, Answer, QuestionBankItem, EvidenceFile, FollowUp,
    VALID_CHOICES, RESPONSE_STATUS_DRAFT, RESPONSE_STATUS_SUBMITTED, RESPONSE_STATUS_NEEDS_INFO
)
from datetime import datetime

UPLOAD_DIR = "uploads"
ALLOWED_EXTENSIONS = {"pdf", "docx", "xlsx", "png", "jpg", "jpeg"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

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
        ).order_by(Response.last_saved_at.desc()).first()
    
    return templates.TemplateResponse("vendor_form.html", {
        "request": request,
        "questionnaire": questionnaire,
        "questions": questions,
        "existing_response": existing_response,
        "RESPONSE_STATUS_SUBMITTED": RESPONSE_STATUS_SUBMITTED,
        "RESPONSE_STATUS_NEEDS_INFO": RESPONSE_STATUS_NEEDS_INFO
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
    ).order_by(Response.last_saved_at.desc()).first()
    
    if existing_response and existing_response.status == RESPONSE_STATUS_SUBMITTED:
        return templates.TemplateResponse("vendor_form.html", {
            "request": request,
            "questionnaire": questionnaire,
            "questions": questions,
            "existing_response": existing_response,
            "RESPONSE_STATUS_SUBMITTED": RESPONSE_STATUS_SUBMITTED,
            "RESPONSE_STATUS_NEEDS_INFO": RESPONSE_STATUS_NEEDS_INFO,
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
            "RESPONSE_STATUS_SUBMITTED": RESPONSE_STATUS_SUBMITTED,
            "RESPONSE_STATUS_NEEDS_INFO": RESPONSE_STATUS_NEEDS_INFO
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
            "RESPONSE_STATUS_NEEDS_INFO": RESPONSE_STATUS_NEEDS_INFO,
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
    ).order_by(Response.last_saved_at.desc()).first()
    
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
        "RESPONSE_STATUS_SUBMITTED": RESPONSE_STATUS_SUBMITTED,
        "RESPONSE_STATUS_NEEDS_INFO": RESPONSE_STATUS_NEEDS_INFO
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
    if status_filter and status_filter in [RESPONSE_STATUS_DRAFT, RESPONSE_STATUS_SUBMITTED, RESPONSE_STATUS_NEEDS_INFO]:
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
        "RESPONSE_STATUS_SUBMITTED": RESPONSE_STATUS_SUBMITTED,
        "RESPONSE_STATUS_NEEDS_INFO": RESPONSE_STATUS_NEEDS_INFO
    })


def sanitize_filename(filename: str) -> str:
    """Sanitize filename to prevent path traversal and unsafe characters."""
    filename = os.path.basename(filename)
    filename = re.sub(r'[^\w\s\-\.]', '', filename)
    filename = filename.strip()
    if not filename:
        filename = "file"
    return filename


def get_file_extension(filename: str) -> str:
    """Get lowercase file extension without the dot."""
    if '.' in filename:
        return filename.rsplit('.', 1)[1].lower()
    return ""


@app.post("/vendor/{token}/upload-evidence")
async def upload_evidence(
    token: str,
    file: UploadFile = File(...),
    vendor_email: str = Form(...),
    vendor_name: str = Form(""),
    db: Session = Depends(get_db)
):
    questionnaire = db.query(Questionnaire).filter(Questionnaire.token == token).first()
    if not questionnaire:
        return JSONResponse(status_code=404, content={"error": "Questionnaire not found"})
    
    ext = get_file_extension(file.filename or "")
    if ext not in ALLOWED_EXTENSIONS:
        return JSONResponse(status_code=400, content={"error": f"File type not allowed. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"})
    
    file_content = await file.read()
    file_size = len(file_content)
    if file_size > MAX_FILE_SIZE:
        return JSONResponse(status_code=400, content={"error": f"File too large. Maximum size is 10MB."})
    
    existing_response = db.query(Response).filter(
        Response.questionnaire_id == questionnaire.id,
        Response.vendor_email == vendor_email
    ).first()
    
    if existing_response and existing_response.status == RESPONSE_STATUS_SUBMITTED:
        return JSONResponse(status_code=400, content={"error": "Cannot upload files after submission."})
    
    if existing_response:
        response = existing_response
    else:
        response = Response(
            questionnaire_id=questionnaire.id,
            vendor_name=vendor_name or "Draft",
            vendor_email=vendor_email,
            status=RESPONSE_STATUS_DRAFT
        )
        db.add(response)
        db.flush()
    
    upload_path = os.path.join(UPLOAD_DIR, str(questionnaire.id), str(response.id))
    os.makedirs(upload_path, exist_ok=True)
    
    original_filename = sanitize_filename(file.filename or "file")
    stored_filename = f"{uuid.uuid4().hex[:8]}_{original_filename}"
    stored_path = os.path.join(upload_path, stored_filename)
    
    with open(stored_path, "wb") as f:
        f.write(file_content)
    
    evidence = EvidenceFile(
        questionnaire_id=questionnaire.id,
        response_id=response.id,
        original_filename=original_filename,
        stored_filename=stored_filename,
        stored_path=stored_path,
        content_type=file.content_type or "application/octet-stream",
        size_bytes=file_size
    )
    db.add(evidence)
    db.commit()
    db.refresh(evidence)
    
    return JSONResponse(content={
        "success": True,
        "file": {
            "id": evidence.id,
            "filename": evidence.original_filename,
            "size": evidence.size_bytes,
            "uploaded_at": evidence.uploaded_at.strftime('%Y-%m-%d %H:%M')
        }
    })


@app.get("/evidence/{evidence_id}")
async def download_evidence(evidence_id: int, db: Session = Depends(get_db)):
    evidence = db.query(EvidenceFile).filter(EvidenceFile.id == evidence_id).first()
    if not evidence:
        raise HTTPException(status_code=404, detail="File not found")
    
    stored_path = str(evidence.stored_path)
    if not os.path.exists(stored_path):
        raise HTTPException(status_code=404, detail="File not found on disk")
    
    return FileResponse(
        path=stored_path,
        filename=str(evidence.original_filename),
        media_type=str(evidence.content_type)
    )


@app.delete("/vendor/{token}/evidence/{evidence_id}")
async def delete_evidence(
    token: str,
    evidence_id: int,
    vendor_email: str,
    db: Session = Depends(get_db)
):
    if not vendor_email or not vendor_email.strip():
        return JSONResponse(status_code=400, content={"error": "Email is required"})
    
    questionnaire = db.query(Questionnaire).filter(Questionnaire.token == token).first()
    if not questionnaire:
        return JSONResponse(status_code=404, content={"error": "Questionnaire not found"})
    
    evidence = db.query(EvidenceFile).filter(
        EvidenceFile.id == evidence_id,
        EvidenceFile.questionnaire_id == questionnaire.id
    ).first()
    if not evidence:
        return JSONResponse(status_code=404, content={"error": "File not found"})
    
    response = db.query(Response).filter(Response.id == evidence.response_id).first()
    if not response:
        return JSONResponse(status_code=404, content={"error": "Response not found"})
    
    if response.vendor_email != vendor_email.strip():
        return JSONResponse(status_code=403, content={"error": "Not authorized to delete this file"})
    
    if response.status == RESPONSE_STATUS_SUBMITTED:
        return JSONResponse(status_code=400, content={"error": "Cannot delete files after submission"})
    
    stored_path = str(evidence.stored_path)
    if os.path.exists(stored_path):
        os.remove(stored_path)
    
    db.delete(evidence)
    db.commit()
    
    return JSONResponse(content={"success": True})


@app.get("/api/vendor/{token}/evidence")
async def get_evidence_list(token: str, email: str, db: Session = Depends(get_db)):
    questionnaire = db.query(Questionnaire).filter(Questionnaire.token == token).first()
    if not questionnaire:
        return JSONResponse(status_code=404, content={"error": "Questionnaire not found"})
    
    response = db.query(Response).filter(
        Response.questionnaire_id == questionnaire.id,
        Response.vendor_email == email
    ).first()
    
    if not response:
        return JSONResponse(content={"files": []})
    
    files = []
    for ev in response.evidence_files:
        files.append({
            "id": ev.id,
            "filename": ev.original_filename,
            "size": ev.size_bytes,
            "uploaded_at": ev.uploaded_at.strftime('%Y-%m-%d %H:%M')
        })
    
    return JSONResponse(content={"files": files})


@app.post("/responses/{questionnaire_id}/followup/{response_id}")
async def create_followup(
    questionnaire_id: int,
    response_id: int,
    message: str = Form(...),
    db: Session = Depends(get_db)
):
    questionnaire = db.query(Questionnaire).filter(Questionnaire.id == questionnaire_id).first()
    if not questionnaire:
        raise HTTPException(status_code=404, detail="Questionnaire not found")
    
    response = db.query(Response).filter(
        Response.id == response_id,
        Response.questionnaire_id == questionnaire_id
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
        url=f"/responses/{questionnaire_id}#response-{response_id}",
        status_code=303
    )


@app.post("/vendor/{token}/followup/{followup_id}")
async def respond_to_followup(
    token: str,
    followup_id: int,
    response_text: str = Form(...),
    vendor_email: str = Form(...),
    db: Session = Depends(get_db)
):
    questionnaire = db.query(Questionnaire).filter(Questionnaire.token == token).first()
    if not questionnaire:
        raise HTTPException(status_code=404, detail="Questionnaire not found")
    
    followup = db.query(FollowUp).filter(FollowUp.id == followup_id).first()
    if not followup:
        raise HTTPException(status_code=404, detail="Follow-up not found")
    
    response = db.query(Response).filter(Response.id == followup.response_id).first()
    if not response or response.questionnaire_id != questionnaire.id:
        raise HTTPException(status_code=404, detail="Response not found")
    
    if response.vendor_email != vendor_email:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    cleaned_response = response_text.strip()
    if not cleaned_response:
        raise HTTPException(status_code=400, detail="Response cannot be empty")
    
    followup.response_text = cleaned_response
    followup.responded_at = datetime.utcnow()
    
    open_followups = db.query(FollowUp).filter(
        FollowUp.response_id == response.id,
        FollowUp.response_text == None
    ).count()
    
    if open_followups == 0:
        response.status = RESPONSE_STATUS_SUBMITTED
    
    db.commit()
    
    return RedirectResponse(
        url=f"/vendor/{token}?email={vendor_email}",
        status_code=303
    )


@app.get("/submissions/{submission_id}/export", response_class=HTMLResponse)
async def export_submission(request: Request, submission_id: int, db: Session = Depends(get_db)):
    response = db.query(Response).filter(Response.id == submission_id).first()
    if not response:
        raise HTTPException(status_code=404, detail="Submission not found")
    
    questionnaire = db.query(Questionnaire).filter(Questionnaire.id == response.questionnaire_id).first()
    
    questions = db.query(Question).filter(
        Question.questionnaire_id == questionnaire.id
    ).order_by(Question.order).all()
    
    answers_dict = {}
    for answer in response.answers:
        answers_dict[answer.question_id] = answer
    
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
        "questionnaire": questionnaire,
        "questions": questions,
        "answers_dict": answers_dict,
        "completion_percent": completion_percent,
        "answered_count": answered_count,
        "evidence_files": evidence_files,
        "follow_ups": follow_ups,
        "RESPONSE_STATUS_DRAFT": RESPONSE_STATUS_DRAFT,
        "RESPONSE_STATUS_SUBMITTED": RESPONSE_STATUS_SUBMITTED,
        "RESPONSE_STATUS_NEEDS_INFO": RESPONSE_STATUS_NEEDS_INFO,
        "now": datetime.utcnow()
    })


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)
