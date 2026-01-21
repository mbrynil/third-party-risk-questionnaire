from fastapi import FastAPI, Request, Form, Depends, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import List, Optional
import uuid
import os
import re
import json

from models import (
    init_db, get_db, seed_question_bank, 
    Questionnaire, Question, Response, Answer, QuestionBankItem, EvidenceFile, FollowUp, ConditionalRule, Vendor,
    AssessmentDecision,
    VALID_CHOICES, RESPONSE_STATUS_DRAFT, RESPONSE_STATUS_SUBMITTED, RESPONSE_STATUS_NEEDS_INFO,
    VENDOR_STATUS_ACTIVE, VENDOR_STATUS_ARCHIVED, VALID_VENDOR_STATUSES,
    ASSESSMENT_STATUS_DRAFT, ASSESSMENT_STATUS_SENT, ASSESSMENT_STATUS_IN_PROGRESS,
    ASSESSMENT_STATUS_SUBMITTED, ASSESSMENT_STATUS_REVIEWED, VALID_ASSESSMENT_STATUSES,
    DECISION_STATUS_DRAFT, DECISION_STATUS_FINAL, VALID_DECISION_STATUSES,
    VALID_RISK_LEVELS, VALID_DECISION_OUTCOMES,
    compute_expectation_status
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
    
    # Normalize inputs
    normalized_company_name = company_name.strip()
    normalized_title = title.strip()
    
    # Generate unique token with retry
    for _ in range(5):
        token = str(uuid.uuid4())[:8]
        existing = db.query(Questionnaire).filter(Questionnaire.token == token).first()
        if not existing:
            break
    
    # Auto-create or link vendor by company_name (case-insensitive)
    vendor = db.query(Vendor).filter(
        Vendor.name.ilike(normalized_company_name)
    ).first()
    
    if not vendor:
        vendor = Vendor(
            name=normalized_company_name,
            status=VENDOR_STATUS_ACTIVE
        )
        db.add(vendor)
        db.flush()
    
    questionnaire = Questionnaire(
        company_name=normalized_company_name, 
        title=normalized_title, 
        token=token,
        vendor_id=vendor.id
    )
    db.add(questionnaire)
    db.flush()
    
    order = 0
    for qid in question_ids:
        bank_item = db.query(QuestionBankItem).filter(QuestionBankItem.id == int(str(qid))).first()
        if bank_item:
            weight = form_data.get(f"weight_{qid}", "MEDIUM")
            if weight not in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]:
                weight = "MEDIUM"
            expected_list = form_data.getlist(f"expected_{qid}[]")
            expected_values_json = None
            expected_value_single = None
            if expected_list:
                valid_expected = [v for v in expected_list if v in VALID_CHOICES]
                if valid_expected:
                    expected_values_json = json.dumps(valid_expected)
                    expected_value_single = valid_expected[0]
            answer_mode = form_data.get(f"answer_mode_{qid}", "SINGLE")
            if answer_mode not in ["SINGLE", "MULTI"]:
                answer_mode = "SINGLE"
            question = Question(
                questionnaire_id=questionnaire.id,
                question_text=bank_item.text,
                order=order,
                weight=weight,
                expected_operator="EQUALS",
                expected_value=expected_value_single,
                expected_values=expected_values_json,
                expected_value_type="CHOICE",
                answer_mode=answer_mode
            )
            db.add(question)
            order += 1
    
    if custom_questions.strip():
        custom_lines = [q.strip() for q in custom_questions.strip().split('\n') if q.strip()]
        for q_text in custom_lines:
            question = Question(
                questionnaire_id=questionnaire.id,
                question_text=q_text,
                order=order,
                weight="MEDIUM",
                expected_operator="EQUALS",
                expected_value=None,
                expected_values=None,
                expected_value_type="CHOICE",
                answer_mode="SINGLE"
            )
            db.add(question)
            order += 1
    
    db.flush()
    
    # Build mapping from bank question ID to actual question ID
    question_id_map = {}
    for q in questionnaire.questions:
        # Map by order to find corresponding bank question ID
        pass
    # Re-query questions to get their IDs
    created_questions = db.query(Question).filter(
        Question.questionnaire_id == questionnaire.id
    ).order_by(Question.order).all()
    
    # Map bank IDs to created question IDs based on order
    for idx, qid in enumerate(question_ids):
        if idx < len(created_questions):
            question_id_map[str(qid)] = created_questions[idx].id
    
    # Process conditional rules
    conditional_rules_json = form_data.get("conditional_rules", "[]")
    try:
        rules_data = json.loads(conditional_rules_json)
        if isinstance(rules_data, list):
            for rule in rules_data:
                trigger_bank_id = str(rule.get("trigger_question_id", ""))
                target_bank_id = str(rule.get("target_question_id", ""))
                trigger_values = rule.get("trigger_values", [])
                make_required = rule.get("make_required", False)
                
                trigger_q_id = question_id_map.get(trigger_bank_id)
                target_q_id = question_id_map.get(target_bank_id)
                
                if trigger_q_id and target_q_id and trigger_values:
                    cond_rule = ConditionalRule(
                        questionnaire_id=questionnaire.id,
                        trigger_question_id=trigger_q_id,
                        operator="IN",
                        trigger_values=json.dumps(trigger_values),
                        target_question_id=target_q_id,
                        make_required=make_required
                    )
                    db.add(cond_rule)
    except (json.JSONDecodeError, TypeError):
        pass
    
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
    questionnaire = db.query(Questionnaire).filter(
        Questionnaire.token == token,
        Questionnaire.is_template == False
    ).first()
    if not questionnaire:
        raise HTTPException(status_code=404, detail="Questionnaire not found")
    
    questions = db.query(Question).filter(
        Question.questionnaire_id == questionnaire.id
    ).order_by(Question.order).all()
    
    conditional_rules = db.query(ConditionalRule).filter(
        ConditionalRule.questionnaire_id == questionnaire.id
    ).all()
    
    # Format rules for JavaScript
    rules_for_js = []
    for rule in conditional_rules:
        try:
            trigger_vals = json.loads(rule.trigger_values)
        except:
            trigger_vals = []
        rules_for_js.append({
            "trigger_question_id": rule.trigger_question_id,
            "trigger_values": trigger_vals,
            "target_question_id": rule.target_question_id,
            "make_required": rule.make_required
        })
    
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
        "conditional_rules": json.dumps(rules_for_js),
        "RESPONSE_STATUS_SUBMITTED": RESPONSE_STATUS_SUBMITTED,
        "RESPONSE_STATUS_NEEDS_INFO": RESPONSE_STATUS_NEEDS_INFO,
        "ASSESSMENT_STATUS_SUBMITTED": ASSESSMENT_STATUS_SUBMITTED,
        "ASSESSMENT_STATUS_REVIEWED": ASSESSMENT_STATUS_REVIEWED
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
    
    # Server-side enforcement: block edits after assessment is submitted
    if questionnaire.status in [ASSESSMENT_STATUS_SUBMITTED, ASSESSMENT_STATUS_REVIEWED]:
        questions = db.query(Question).filter(
            Question.questionnaire_id == questionnaire.id
        ).order_by(Question.order).all()
        existing_response = db.query(Response).filter(
            Response.questionnaire_id == questionnaire.id,
            Response.status == RESPONSE_STATUS_SUBMITTED
        ).first()
        return templates.TemplateResponse("vendor_form.html", {
            "request": request,
            "questionnaire": questionnaire,
            "questions": questions,
            "existing_response": existing_response,
            "RESPONSE_STATUS_SUBMITTED": RESPONSE_STATUS_SUBMITTED,
            "RESPONSE_STATUS_NEEDS_INFO": RESPONSE_STATUS_NEEDS_INFO,
            "ASSESSMENT_STATUS_SUBMITTED": ASSESSMENT_STATUS_SUBMITTED,
            "ASSESSMENT_STATUS_REVIEWED": ASSESSMENT_STATUS_REVIEWED,
            "error": "This assessment has already been submitted and cannot be edited."
        })
    
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
            "ASSESSMENT_STATUS_SUBMITTED": ASSESSMENT_STATUS_SUBMITTED,
            "ASSESSMENT_STATUS_REVIEWED": ASSESSMENT_STATUS_REVIEWED,
            "error": "You have already submitted this questionnaire. Editing is no longer allowed."
        })
    
    if action == "submit":
        missing_answers = []
        for question in questions:
            if question.answer_mode == "MULTI":
                multi_key = f"multi_{question.id}[]"
                multi_values = form_data.getlist(multi_key)
                if not multi_values:
                    missing_answers.append(question)
            else:
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
        notes_key = f"notes_{question.id}"
        notes_value = str(form_data.get(notes_key, "")).strip() or None
        
        if question.answer_mode == "MULTI":
            multi_key = f"multi_{question.id}[]"
            multi_values = form_data.getlist(multi_key)
            valid_multi = [v for v in multi_values if v in VALID_CHOICES]
            choice_value = ",".join(valid_multi) if valid_multi else None
        else:
            choice_key = f"choice_{question.id}"
            choice_value = form_data.get(choice_key, "") or None
            choice_value = choice_value if choice_value in VALID_CHOICES else None
        
        answer = Answer(
            response_id=response.id,
            question_id=question.id,
            answer_choice=choice_value,
            notes=notes_value
        )
        db.add(answer)
    
    # Update assessment lifecycle status
    if action == "submit":
        # Transition to SUBMITTED (from SENT or IN_PROGRESS)
        if questionnaire.status in [ASSESSMENT_STATUS_SENT, ASSESSMENT_STATUS_IN_PROGRESS]:
            questionnaire.status = ASSESSMENT_STATUS_SUBMITTED
            questionnaire.submitted_at = datetime.utcnow()
    else:
        # Save draft: transition SENT → IN_PROGRESS on first interaction
        if questionnaire.status == ASSESSMENT_STATUS_SENT:
            questionnaire.status = ASSESSMENT_STATUS_IN_PROGRESS
    
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
            "ASSESSMENT_STATUS_SUBMITTED": ASSESSMENT_STATUS_SUBMITTED,
            "ASSESSMENT_STATUS_REVIEWED": ASSESSMENT_STATUS_REVIEWED,
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
    questionnaires = db.query(Questionnaire).filter(Questionnaire.is_template == False).all()
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
    
    eval_dicts = {}
    for resp in responses:
        answers_dict = {a.question_id: a for a in resp.answers}
        eval_dict = {}
        for q in questions:
            answer = answers_dict.get(q.id)
            answer_choice = answer.answer_choice if answer else None
            eval_dict[q.id] = compute_expectation_status(q.expected_value, answer_choice, q.expected_values, q.answer_mode)
        eval_dicts[resp.id] = eval_dict
    
    return templates.TemplateResponse("questionnaire_responses.html", {
        "request": request,
        "questionnaire": questionnaire,
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
    
    eval_dict = {}
    for q in questions:
        answer = answers_dict.get(q.id)
        answer_choice = answer.answer_choice if answer else None
        eval_dict[q.id] = compute_expectation_status(q.expected_value, answer_choice)
    
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


@app.get("/templates", response_class=HTMLResponse)
async def view_templates(request: Request, db: Session = Depends(get_db)):
    templates_list = db.query(Questionnaire).filter(Questionnaire.is_template == True).order_by(Questionnaire.created_at.desc()).all()
    return templates.TemplateResponse("templates_list.html", {
        "request": request,
        "templates": templates_list
    })


@app.post("/questionnaires/{questionnaire_id}/save-as-template")
async def save_as_template(
    request: Request,
    questionnaire_id: int,
    template_name: str = Form(...),
    template_description: str = Form(""),
    db: Session = Depends(get_db)
):
    source = db.query(Questionnaire).filter(Questionnaire.id == questionnaire_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Questionnaire not found")
    
    # Generate unique token with retry
    for _ in range(5):
        token = str(uuid.uuid4())[:8]
        existing = db.query(Questionnaire).filter(Questionnaire.token == token).first()
        if not existing:
            break
    
    new_template = Questionnaire(
        company_name=source.company_name,
        title=source.title,
        token=token,
        is_template=True,
        template_name=template_name.strip(),
        template_description=template_description.strip() if template_description else None
    )
    db.add(new_template)
    db.flush()
    
    question_id_map = {}
    source_questions = db.query(Question).filter(Question.questionnaire_id == source.id).order_by(Question.order).all()
    for sq in source_questions:
        new_q = Question(
            questionnaire_id=new_template.id,
            question_text=sq.question_text,
            order=sq.order,
            weight=sq.weight,
            expected_operator=sq.expected_operator,
            expected_value=sq.expected_value,
            expected_values=sq.expected_values,
            expected_value_type=sq.expected_value_type,
            answer_mode=sq.answer_mode
        )
        db.add(new_q)
        db.flush()
        question_id_map[sq.id] = new_q.id
    
    source_rules = db.query(ConditionalRule).filter(ConditionalRule.questionnaire_id == source.id).all()
    for rule in source_rules:
        new_trigger = question_id_map.get(rule.trigger_question_id)
        new_target = question_id_map.get(rule.target_question_id)
        if new_trigger and new_target:
            new_rule = ConditionalRule(
                questionnaire_id=new_template.id,
                trigger_question_id=new_trigger,
                operator=rule.operator,
                trigger_values=rule.trigger_values,
                target_question_id=new_target,
                make_required=rule.make_required
            )
            db.add(new_rule)
    
    db.commit()
    
    return RedirectResponse(url="/templates?saved=1", status_code=303)


@app.post("/templates/{template_id}/create-questionnaire")
async def create_from_template(
    request: Request,
    template_id: int,
    company_name: str = Form(...),
    title: str = Form(...),
    db: Session = Depends(get_db)
):
    source = db.query(Questionnaire).filter(
        Questionnaire.id == template_id,
        Questionnaire.is_template == True
    ).first()
    if not source:
        raise HTTPException(status_code=404, detail="Template not found")
    
    # Normalize inputs
    normalized_company_name = company_name.strip()
    normalized_title = title.strip()
    
    # Generate unique token with retry
    for _ in range(5):
        token = str(uuid.uuid4())[:8]
        existing = db.query(Questionnaire).filter(Questionnaire.token == token).first()
        if not existing:
            break
    
    # Auto-create or link vendor by company_name (case-insensitive)
    vendor = db.query(Vendor).filter(
        Vendor.name.ilike(normalized_company_name)
    ).first()
    
    if not vendor:
        vendor = Vendor(
            name=normalized_company_name,
            status=VENDOR_STATUS_ACTIVE
        )
        db.add(vendor)
        db.flush()
    
    new_questionnaire = Questionnaire(
        company_name=normalized_company_name,
        title=normalized_title,
        token=token,
        is_template=False,
        template_name=None,
        template_description=None,
        vendor_id=vendor.id
    )
    db.add(new_questionnaire)
    db.flush()
    
    question_id_map = {}
    source_questions = db.query(Question).filter(Question.questionnaire_id == source.id).order_by(Question.order).all()
    for sq in source_questions:
        new_q = Question(
            questionnaire_id=new_questionnaire.id,
            question_text=sq.question_text,
            order=sq.order,
            weight=sq.weight,
            expected_operator=sq.expected_operator,
            expected_value=sq.expected_value,
            expected_values=sq.expected_values,
            expected_value_type=sq.expected_value_type,
            answer_mode=sq.answer_mode
        )
        db.add(new_q)
        db.flush()
        question_id_map[sq.id] = new_q.id
    
    source_rules = db.query(ConditionalRule).filter(ConditionalRule.questionnaire_id == source.id).all()
    for rule in source_rules:
        new_trigger = question_id_map.get(rule.trigger_question_id)
        new_target = question_id_map.get(rule.target_question_id)
        if new_trigger and new_target:
            new_rule = ConditionalRule(
                questionnaire_id=new_questionnaire.id,
                trigger_question_id=new_trigger,
                operator=rule.operator,
                trigger_values=rule.trigger_values,
                target_question_id=new_target,
                make_required=rule.make_required
            )
            db.add(new_rule)
    
    db.commit()
    
    return RedirectResponse(url=f"/questionnaire/{new_questionnaire.id}/edit?from_template=1", status_code=303)


@app.get("/questionnaire/{questionnaire_id}/edit", response_class=HTMLResponse)
async def edit_questionnaire_page(request: Request, questionnaire_id: int, db: Session = Depends(get_db)):
    questionnaire = db.query(Questionnaire).filter(
        Questionnaire.id == questionnaire_id,
        Questionnaire.is_template == False
    ).first()
    if not questionnaire:
        raise HTTPException(status_code=404, detail="Questionnaire not found")
    
    questions = db.query(Question).filter(
        Question.questionnaire_id == questionnaire.id
    ).order_by(Question.order).all()
    
    rules = db.query(ConditionalRule).filter(
        ConditionalRule.questionnaire_id == questionnaire.id
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
        "questionnaire": questionnaire,
        "questions": questions,
        "rules": rules,
        "categories": categories
    })


@app.post("/questionnaire/{questionnaire_id}/edit")
async def update_questionnaire(
    request: Request,
    questionnaire_id: int,
    company_name: str = Form(...),
    title: str = Form(...),
    db: Session = Depends(get_db)
):
    questionnaire = db.query(Questionnaire).filter(
        Questionnaire.id == questionnaire_id,
        Questionnaire.is_template == False
    ).first()
    if not questionnaire:
        raise HTTPException(status_code=404, detail="Questionnaire not found")
    
    form_data = await request.form()
    
    questionnaire.company_name = company_name.strip()
    questionnaire.title = title.strip()
    
    questions = db.query(Question).filter(
        Question.questionnaire_id == questionnaire.id
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
    
    return RedirectResponse(url=f"/questionnaire/{questionnaire_id}/edit?saved=1", status_code=303)


@app.get("/questionnaire/{questionnaire_id}/share", response_class=HTMLResponse)
async def share_questionnaire(request: Request, questionnaire_id: int, db: Session = Depends(get_db)):
    questionnaire = db.query(Questionnaire).filter(
        Questionnaire.id == questionnaire_id,
        Questionnaire.is_template == False
    ).first()
    if not questionnaire:
        raise HTTPException(status_code=404, detail="Questionnaire not found")
    
    # Transition DRAFT → SENT when accessing share link
    if questionnaire.status == ASSESSMENT_STATUS_DRAFT:
        questionnaire.status = ASSESSMENT_STATUS_SENT
        questionnaire.sent_at = datetime.utcnow()
        db.commit()
    
    base_url = str(request.base_url).rstrip('/')
    vendor_url = f"{base_url}/vendor/{questionnaire.token}"
    
    return templates.TemplateResponse("created.html", {
        "request": request,
        "questionnaire": questionnaire,
        "token": questionnaire.token,
        "vendor_url": vendor_url
    })


@app.post("/questionnaire/{questionnaire_id}/add-questions")
async def add_questions_to_questionnaire(
    request: Request,
    questionnaire_id: int,
    bank_ids: str = Form(""),
    custom_text: str = Form(""),
    db: Session = Depends(get_db)
):
    questionnaire = db.query(Questionnaire).filter(
        Questionnaire.id == questionnaire_id,
        Questionnaire.is_template == False
    ).first()
    if not questionnaire:
        raise HTTPException(status_code=404, detail="Questionnaire not found")
    
    max_order = db.query(Question).filter(
        Question.questionnaire_id == questionnaire.id
    ).count()
    
    order = max_order
    
    if bank_ids.strip():
        for qid in bank_ids.split(','):
            qid = qid.strip()
            if qid:
                bank_item = db.query(QuestionBankItem).filter(QuestionBankItem.id == int(qid)).first()
                if bank_item:
                    question = Question(
                        questionnaire_id=questionnaire.id,
                        question_text=bank_item.text,
                        order=order,
                        weight="MEDIUM",
                        expected_operator="EQUALS",
                        expected_value=None,
                        expected_values=None,
                        expected_value_type="CHOICE",
                        answer_mode="SINGLE"
                    )
                    db.add(question)
                    order += 1
    
    if custom_text.strip():
        question = Question(
            questionnaire_id=questionnaire.id,
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
    
    return RedirectResponse(url=f"/questionnaire/{questionnaire_id}/edit", status_code=303)


@app.post("/questionnaire/{questionnaire_id}/remove-question")
async def remove_question_from_questionnaire(
    questionnaire_id: int,
    question_id: int = Form(...),
    db: Session = Depends(get_db)
):
    question = db.query(Question).filter(
        Question.id == question_id,
        Question.questionnaire_id == questionnaire_id
    ).first()
    if question:
        db.query(ConditionalRule).filter(
            (ConditionalRule.trigger_question_id == question_id) |
            (ConditionalRule.target_question_id == question_id)
        ).delete()
        db.delete(question)
        db.commit()
    
    return RedirectResponse(url=f"/questionnaire/{questionnaire_id}/edit", status_code=303)


@app.post("/questionnaire/{questionnaire_id}/add-rule")
async def add_rule_to_questionnaire(
    questionnaire_id: int,
    trigger_id: int = Form(...),
    target_id: int = Form(...),
    trigger_values: str = Form(...),
    make_required: str = Form("0"),
    db: Session = Depends(get_db)
):
    questionnaire = db.query(Questionnaire).filter(
        Questionnaire.id == questionnaire_id,
        Questionnaire.is_template == False
    ).first()
    if not questionnaire:
        raise HTTPException(status_code=404, detail="Questionnaire not found")
    
    rule = ConditionalRule(
        questionnaire_id=questionnaire.id,
        trigger_question_id=trigger_id,
        operator="IN",
        trigger_values=trigger_values,
        target_question_id=target_id,
        make_required=(make_required == "1")
    )
    db.add(rule)
    db.commit()
    
    return RedirectResponse(url=f"/questionnaire/{questionnaire_id}/edit", status_code=303)


@app.post("/questionnaire/{questionnaire_id}/delete-rule")
async def delete_rule_from_questionnaire(
    questionnaire_id: int,
    rule_id: int = Form(...),
    db: Session = Depends(get_db)
):
    rule = db.query(ConditionalRule).filter(
        ConditionalRule.id == rule_id,
        ConditionalRule.questionnaire_id == questionnaire_id
    ).first()
    if rule:
        db.delete(rule)
        db.commit()
    
    return RedirectResponse(url=f"/questionnaire/{questionnaire_id}/edit", status_code=303)


@app.post("/templates/{template_id}/delete")
async def delete_template(template_id: int, db: Session = Depends(get_db)):
    template = db.query(Questionnaire).filter(
        Questionnaire.id == template_id,
        Questionnaire.is_template == True
    ).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    db.delete(template)
    db.commit()
    
    return RedirectResponse(url="/templates?deleted=1", status_code=303)


@app.post("/questionnaire/{questionnaire_id}/mark-reviewed")
async def mark_questionnaire_reviewed(
    questionnaire_id: int,
    db: Session = Depends(get_db)
):
    questionnaire = db.query(Questionnaire).filter(
        Questionnaire.id == questionnaire_id,
        Questionnaire.is_template == False
    ).first()
    if not questionnaire:
        raise HTTPException(status_code=404, detail="Questionnaire not found")
    
    # Only allow marking as reviewed if currently SUBMITTED
    if questionnaire.status == ASSESSMENT_STATUS_SUBMITTED:
        questionnaire.status = ASSESSMENT_STATUS_REVIEWED
        questionnaire.reviewed_at = datetime.utcnow()
        db.commit()
    
    return RedirectResponse(url=f"/responses/{questionnaire_id}?marked_reviewed=1", status_code=303)


# ==================== VENDOR ROUTES ====================

@app.get("/vendors", response_class=HTMLResponse)
async def vendors_list(request: Request, db: Session = Depends(get_db)):
    vendors = db.query(Vendor).order_by(Vendor.name).all()
    return templates.TemplateResponse("vendors.html", {
        "request": request,
        "vendors": vendors
    })


@app.get("/vendors/new", response_class=HTMLResponse)
async def new_vendor_page(request: Request):
    return templates.TemplateResponse("vendor_edit.html", {
        "request": request,
        "vendor": None
    })


@app.post("/vendors/new")
async def create_vendor(
    request: Request,
    name: str = Form(...),
    primary_contact_name: str = Form(""),
    primary_contact_email: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db)
):
    if not name.strip():
        return templates.TemplateResponse("vendor_edit.html", {
            "request": request,
            "vendor": None,
            "error": "Vendor name is required."
        })
    
    vendor = Vendor(
        name=name.strip(),
        primary_contact_name=primary_contact_name.strip() if primary_contact_name else None,
        primary_contact_email=primary_contact_email.strip() if primary_contact_email else None,
        notes=notes.strip() if notes else None,
        status=VENDOR_STATUS_ACTIVE
    )
    db.add(vendor)
    db.commit()
    
    return RedirectResponse(url=f"/vendors/{vendor.id}?created=1", status_code=303)


@app.get("/vendors/{vendor_id}", response_class=HTMLResponse)
async def vendor_profile(request: Request, vendor_id: int, db: Session = Depends(get_db)):
    vendor = db.query(Vendor).filter(Vendor.id == vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")
    
    assessments = db.query(Questionnaire).filter(
        Questionnaire.vendor_id == vendor_id,
        Questionnaire.is_template == False
    ).order_by(Questionnaire.created_at.desc()).all()
    
    templates_list = db.query(Questionnaire).filter(
        Questionnaire.is_template == True
    ).order_by(Questionnaire.template_name).all()
    
    questionnaire_ids = [a.id for a in assessments]
    assessment_decisions = db.query(AssessmentDecision).filter(
        AssessmentDecision.questionnaire_id.in_(questionnaire_ids)
    ).all() if questionnaire_ids else []
    decisions = {d.questionnaire_id: d for d in assessment_decisions}
    
    return templates.TemplateResponse("vendor_profile.html", {
        "request": request,
        "vendor": vendor,
        "assessments": assessments,
        "templates": templates_list,
        "decisions": decisions
    })


@app.get("/vendors/{vendor_id}/edit", response_class=HTMLResponse)
async def edit_vendor_page(request: Request, vendor_id: int, db: Session = Depends(get_db)):
    vendor = db.query(Vendor).filter(Vendor.id == vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")
    
    return templates.TemplateResponse("vendor_edit.html", {
        "request": request,
        "vendor": vendor
    })


@app.post("/vendors/{vendor_id}/edit")
async def update_vendor(
    request: Request,
    vendor_id: int,
    name: str = Form(...),
    primary_contact_name: str = Form(""),
    primary_contact_email: str = Form(""),
    notes: str = Form(""),
    status: str = Form("ACTIVE"),
    db: Session = Depends(get_db)
):
    vendor = db.query(Vendor).filter(Vendor.id == vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")
    
    if not name.strip():
        return templates.TemplateResponse("vendor_edit.html", {
            "request": request,
            "vendor": vendor,
            "error": "Vendor name is required."
        })
    
    vendor.name = name.strip()
    vendor.primary_contact_name = primary_contact_name.strip() if primary_contact_name else None
    vendor.primary_contact_email = primary_contact_email.strip() if primary_contact_email else None
    vendor.notes = notes.strip() if notes else None
    if status in VALID_VENDOR_STATUSES:
        vendor.status = status
    
    db.commit()
    
    return RedirectResponse(url=f"/vendors/{vendor_id}?updated=1", status_code=303)


@app.post("/vendors/{vendor_id}/create-assessment")
async def create_vendor_assessment(
    request: Request,
    vendor_id: int,
    source: str = Form(...),
    title: str = Form(...),
    template_id: Optional[int] = Form(None),
    db: Session = Depends(get_db)
):
    vendor = db.query(Vendor).filter(Vendor.id == vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")
    
    # Generate unique token with retry
    for _ in range(5):
        token = str(uuid.uuid4())[:8]
        existing = db.query(Questionnaire).filter(Questionnaire.token == token).first()
        if not existing:
            break
    
    if source == "template" and template_id:
        template = db.query(Questionnaire).filter(
            Questionnaire.id == template_id,
            Questionnaire.is_template == True
        ).first()
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")
        
        new_questionnaire = Questionnaire(
            company_name=vendor.name,
            title=title.strip(),
            token=token,
            is_template=False,
            vendor_id=vendor.id
        )
        db.add(new_questionnaire)
        db.flush()
        
        question_id_map = {}
        source_questions = db.query(Question).filter(Question.questionnaire_id == template.id).order_by(Question.order).all()
        for sq in source_questions:
            new_q = Question(
                questionnaire_id=new_questionnaire.id,
                question_text=sq.question_text,
                order=sq.order,
                weight=sq.weight,
                expected_operator=sq.expected_operator,
                expected_value=sq.expected_value,
                expected_values=sq.expected_values,
                expected_value_type=sq.expected_value_type,
                answer_mode=sq.answer_mode
            )
            db.add(new_q)
            db.flush()
            question_id_map[sq.id] = new_q.id
        
        source_rules = db.query(ConditionalRule).filter(ConditionalRule.questionnaire_id == template.id).all()
        for rule in source_rules:
            new_trigger = question_id_map.get(rule.trigger_question_id)
            new_target = question_id_map.get(rule.target_question_id)
            if new_trigger and new_target:
                new_rule = ConditionalRule(
                    questionnaire_id=new_questionnaire.id,
                    trigger_question_id=new_trigger,
                    operator=rule.operator,
                    trigger_values=rule.trigger_values,
                    target_question_id=new_target,
                    make_required=rule.make_required
                )
                db.add(new_rule)
        
        db.commit()
        return RedirectResponse(url=f"/questionnaire/{new_questionnaire.id}/edit?from_template=1", status_code=303)
    
    else:
        new_questionnaire = Questionnaire(
            company_name=vendor.name,
            title=title.strip(),
            token=token,
            is_template=False,
            vendor_id=vendor.id
        )
        db.add(new_questionnaire)
        db.commit()
        
        return RedirectResponse(url=f"/create?vendor_id={vendor.id}&questionnaire_id={new_questionnaire.id}", status_code=303)


@app.get("/assessments/{questionnaire_id}/decision", response_class=HTMLResponse)
async def assessment_decision_page(request: Request, questionnaire_id: int, db: Session = Depends(get_db)):
    questionnaire = db.query(Questionnaire).filter(Questionnaire.id == questionnaire_id).first()
    if not questionnaire:
        raise HTTPException(status_code=404, detail="Questionnaire not found")
    
    if not questionnaire.vendor_id:
        raise HTTPException(status_code=400, detail="Questionnaire has no linked vendor")
    
    vendor = db.query(Vendor).filter(Vendor.id == questionnaire.vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")
    
    decision = db.query(AssessmentDecision).filter(
        AssessmentDecision.questionnaire_id == questionnaire_id
    ).first()
    
    if not decision:
        decision = AssessmentDecision(
            vendor_id=vendor.id,
            questionnaire_id=questionnaire_id,
            status=DECISION_STATUS_DRAFT
        )
        db.add(decision)
        db.commit()
        db.refresh(decision)
    
    response = db.query(Response).filter(
        Response.questionnaire_id == questionnaire_id,
        Response.status == RESPONSE_STATUS_SUBMITTED
    ).first()
    
    questions = db.query(Question).filter(Question.questionnaire_id == questionnaire_id).order_by(Question.order).all()
    
    meets_count = 0
    partial_count = 0
    does_not_meet_count = 0
    no_expectation_count = 0
    
    if response:
        answers = {a.question_id: a for a in response.answers}
        for q in questions:
            answer = answers.get(q.id)
            if answer:
                status = compute_expectation_status(
                    q.expected_value, 
                    answer.answer_choice, 
                    q.expected_values, 
                    q.answer_mode
                )
                if status == "MEETS_EXPECTATION":
                    meets_count += 1
                elif status == "PARTIALLY_MEETS_EXPECTATION":
                    partial_count += 1
                elif status == "DOES_NOT_MEET_EXPECTATION":
                    does_not_meet_count += 1
                else:
                    no_expectation_count += 1
            else:
                no_expectation_count += 1
    
    return templates.TemplateResponse("assessment_decision.html", {
        "request": request,
        "questionnaire": questionnaire,
        "vendor": vendor,
        "decision": decision,
        "response": response,
        "total_questions": len(questions),
        "meets_count": meets_count,
        "partial_count": partial_count,
        "does_not_meet_count": does_not_meet_count,
        "no_expectation_count": no_expectation_count,
        "risk_levels": VALID_RISK_LEVELS,
        "decision_outcomes": VALID_DECISION_OUTCOMES
    })


@app.post("/assessments/{questionnaire_id}/decision", response_class=HTMLResponse)
async def save_assessment_decision(
    request: Request,
    questionnaire_id: int,
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
    questionnaire = db.query(Questionnaire).filter(Questionnaire.id == questionnaire_id).first()
    if not questionnaire:
        raise HTTPException(status_code=404, detail="Questionnaire not found")
    
    decision = db.query(AssessmentDecision).filter(
        AssessmentDecision.questionnaire_id == questionnaire_id
    ).first()
    
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")
    
    if decision.status == DECISION_STATUS_FINAL:
        return RedirectResponse(
            url=f"/vendors/{questionnaire.vendor_id}?message=Assessment already finalized&message_type=warning",
            status_code=303
        )
    
    decision.data_sensitivity = data_sensitivity if data_sensitivity else None
    decision.business_criticality = business_criticality if business_criticality else None
    decision.impact_rating = impact_rating if impact_rating else None
    decision.likelihood_rating = likelihood_rating if likelihood_rating else None
    decision.overall_risk_rating = overall_risk_rating if overall_risk_rating else None
    decision.decision_outcome = decision_outcome if decision_outcome else None
    decision.rationale = rationale.strip() if rationale else None
    decision.key_findings = key_findings.strip() if key_findings else None
    decision.remediation_required = remediation_required.strip() if remediation_required else None
    
    if next_review_date:
        try:
            decision.next_review_date = datetime.strptime(next_review_date, "%Y-%m-%d")
        except ValueError:
            decision.next_review_date = None
    else:
        decision.next_review_date = None
    
    if action == "finalize":
        required_fields = [
            data_sensitivity, business_criticality, impact_rating,
            likelihood_rating, overall_risk_rating, decision_outcome
        ]
        if not all(required_fields):
            return RedirectResponse(
                url=f"/assessments/{questionnaire_id}/decision?message=Please fill all required fields before finalizing&message_type=danger",
                status_code=303
            )
        
        decision.status = DECISION_STATUS_FINAL
        decision.finalized_at = datetime.utcnow()
        
        if questionnaire.status == ASSESSMENT_STATUS_SUBMITTED:
            questionnaire.status = ASSESSMENT_STATUS_REVIEWED
            questionnaire.reviewed_at = datetime.utcnow()
    
    db.commit()
    
    if action == "finalize":
        return RedirectResponse(
            url=f"/vendors/{questionnaire.vendor_id}?message=Assessment finalized successfully&message_type=success",
            status_code=303
        )
    else:
        return RedirectResponse(
            url=f"/assessments/{questionnaire_id}/decision?message=Draft saved&message_type=success",
            status_code=303
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)
