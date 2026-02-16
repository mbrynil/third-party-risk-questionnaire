from fastapi import APIRouter, Request, Form, Depends, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime
import os
import json

from app import templates
from models import (
    get_db, Assessment, Question, Response, EvidenceFile, FollowUp, ConditionalRule,
    RESPONSE_STATUS_DRAFT, RESPONSE_STATUS_SUBMITTED, RESPONSE_STATUS_NEEDS_INFO,
    ASSESSMENT_STATUS_SUBMITTED, ASSESSMENT_STATUS_REVIEWED,
)
from app.services.response_service import validate_answers, save_or_update_response
from app.services.evidence_service import validate_upload, store_file
from app.services.lifecycle import transition_to_submitted, transition_to_in_progress

router = APIRouter()


@router.get("/vendor/{token}", response_class=HTMLResponse)
async def vendor_form(request: Request, token: str, email: Optional[str] = None, db: Session = Depends(get_db)):
    assessment = db.query(Assessment).filter(
        Assessment.token == token
    ).first()
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")

    questions = db.query(Question).filter(
        Question.assessment_id == assessment.id
    ).order_by(Question.order).all()

    conditional_rules = db.query(ConditionalRule).filter(
        ConditionalRule.assessment_id == assessment.id
    ).all()

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
            Response.assessment_id == assessment.id,
            Response.vendor_email == email
        ).order_by(Response.last_saved_at.desc()).first()

    return templates.TemplateResponse("vendor_form.html", {
        "request": request,
        "assessment": assessment,
        "questions": questions,
        "existing_response": existing_response,
        "conditional_rules": json.dumps(rules_for_js),
        "RESPONSE_STATUS_SUBMITTED": RESPONSE_STATUS_SUBMITTED,
        "RESPONSE_STATUS_NEEDS_INFO": RESPONSE_STATUS_NEEDS_INFO,
        "ASSESSMENT_STATUS_SUBMITTED": ASSESSMENT_STATUS_SUBMITTED,
        "ASSESSMENT_STATUS_REVIEWED": ASSESSMENT_STATUS_REVIEWED
    })


@router.post("/vendor/{token}")
async def submit_vendor_response(
    request: Request,
    token: str,
    db: Session = Depends(get_db)
):
    assessment = db.query(Assessment).filter(Assessment.token == token).first()
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")

    if assessment.status in [ASSESSMENT_STATUS_SUBMITTED, ASSESSMENT_STATUS_REVIEWED]:
        questions = db.query(Question).filter(
            Question.assessment_id == assessment.id
        ).order_by(Question.order).all()
        existing_response = db.query(Response).filter(
            Response.assessment_id == assessment.id,
            Response.status == RESPONSE_STATUS_SUBMITTED
        ).first()
        return templates.TemplateResponse("vendor_form.html", {
            "request": request,
            "assessment": assessment,
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
        Question.assessment_id == assessment.id
    ).order_by(Question.order).all()

    errors = []
    if not vendor_name:
        errors.append("Company name is required.")
    if not vendor_email:
        errors.append("Contact email is required.")

    existing_response = db.query(Response).filter(
        Response.assessment_id == assessment.id,
        Response.vendor_email == vendor_email
    ).order_by(Response.last_saved_at.desc()).first()

    if existing_response and existing_response.status == RESPONSE_STATUS_SUBMITTED:
        return templates.TemplateResponse("vendor_form.html", {
            "request": request,
            "assessment": assessment,
            "questions": questions,
            "existing_response": existing_response,
            "RESPONSE_STATUS_SUBMITTED": RESPONSE_STATUS_SUBMITTED,
            "RESPONSE_STATUS_NEEDS_INFO": RESPONSE_STATUS_NEEDS_INFO,
            "ASSESSMENT_STATUS_SUBMITTED": ASSESSMENT_STATUS_SUBMITTED,
            "ASSESSMENT_STATUS_REVIEWED": ASSESSMENT_STATUS_REVIEWED,
            "error": "You have already submitted this questionnaire. Editing is no longer allowed."
        })

    answer_errors = validate_answers(questions, form_data, action)
    errors.extend(answer_errors)

    if errors:
        return templates.TemplateResponse("vendor_form.html", {
            "request": request,
            "assessment": assessment,
            "questions": questions,
            "error": " ".join(errors),
            "form_data": dict(form_data),
            "RESPONSE_STATUS_SUBMITTED": RESPONSE_STATUS_SUBMITTED,
            "RESPONSE_STATUS_NEEDS_INFO": RESPONSE_STATUS_NEEDS_INFO
        })

    response = save_or_update_response(
        db, assessment.id, vendor_name, vendor_email,
        action, questions, form_data, existing_response
    )

    if action == "submit":
        transition_to_submitted(db, assessment)
    else:
        transition_to_in_progress(db, assessment)

    db.commit()

    if action == "submit":
        return templates.TemplateResponse("submitted.html", {"request": request})
    else:
        db.refresh(response)
        return templates.TemplateResponse("vendor_form.html", {
            "request": request,
            "assessment": assessment,
            "questions": questions,
            "existing_response": response,
            "RESPONSE_STATUS_SUBMITTED": RESPONSE_STATUS_SUBMITTED,
            "RESPONSE_STATUS_NEEDS_INFO": RESPONSE_STATUS_NEEDS_INFO,
            "ASSESSMENT_STATUS_SUBMITTED": ASSESSMENT_STATUS_SUBMITTED,
            "ASSESSMENT_STATUS_REVIEWED": ASSESSMENT_STATUS_REVIEWED,
            "success": f"Draft saved at {response.last_saved_at.strftime('%Y-%m-%d %H:%M:%S')} UTC"
        })


@router.get("/api/vendor/{token}/check-draft")
async def check_draft(token: str, email: str, db: Session = Depends(get_db)):
    assessment = db.query(Assessment).filter(Assessment.token == token).first()
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")

    response = db.query(Response).filter(
        Response.assessment_id == assessment.id,
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


@router.post("/vendor/{token}/upload-evidence")
async def upload_evidence(
    token: str,
    file: UploadFile = File(...),
    vendor_email: str = Form(...),
    vendor_name: str = Form(""),
    db: Session = Depends(get_db)
):
    assessment = db.query(Assessment).filter(Assessment.token == token).first()
    if not assessment:
        return JSONResponse(status_code=404, content={"error": "Assessment not found"})

    file_content = await file.read()
    error = validate_upload(file.filename or "", len(file_content))
    if error:
        return JSONResponse(status_code=400, content={"error": error})

    existing_response = db.query(Response).filter(
        Response.assessment_id == assessment.id,
        Response.vendor_email == vendor_email
    ).first()

    if existing_response and existing_response.status == RESPONSE_STATUS_SUBMITTED:
        return JSONResponse(status_code=400, content={"error": "Cannot upload files after submission."})

    if existing_response:
        response = existing_response
    else:
        response = Response(
            assessment_id=assessment.id,
            vendor_name=vendor_name or "Draft",
            vendor_email=vendor_email,
            status=RESPONSE_STATUS_DRAFT
        )
        db.add(response)
        db.flush()

    original_filename, stored_filename, stored_path = store_file(
        file_content, file.filename or "file", assessment.id, response.id
    )

    evidence = EvidenceFile(
        assessment_id=assessment.id,
        response_id=response.id,
        original_filename=original_filename,
        stored_filename=stored_filename,
        stored_path=stored_path,
        content_type=file.content_type or "application/octet-stream",
        size_bytes=len(file_content)
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


@router.get("/evidence/{evidence_id}")
async def download_evidence(evidence_id: int, db: Session = Depends(get_db)):
    from fastapi.responses import FileResponse
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


@router.delete("/vendor/{token}/evidence/{evidence_id}")
async def delete_evidence(
    token: str,
    evidence_id: int,
    vendor_email: str,
    db: Session = Depends(get_db)
):
    if not vendor_email or not vendor_email.strip():
        return JSONResponse(status_code=400, content={"error": "Email is required"})

    assessment = db.query(Assessment).filter(Assessment.token == token).first()
    if not assessment:
        return JSONResponse(status_code=404, content={"error": "Assessment not found"})

    evidence = db.query(EvidenceFile).filter(
        EvidenceFile.id == evidence_id,
        EvidenceFile.assessment_id == assessment.id
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


@router.get("/api/vendor/{token}/evidence")
async def get_evidence_list(token: str, email: str, db: Session = Depends(get_db)):
    assessment = db.query(Assessment).filter(Assessment.token == token).first()
    if not assessment:
        return JSONResponse(status_code=404, content={"error": "Assessment not found"})

    response = db.query(Response).filter(
        Response.assessment_id == assessment.id,
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


@router.post("/vendor/{token}/followup/{followup_id}")
async def respond_to_followup(
    token: str,
    followup_id: int,
    response_text: str = Form(...),
    vendor_email: str = Form(...),
    db: Session = Depends(get_db)
):
    assessment = db.query(Assessment).filter(Assessment.token == token).first()
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")

    followup = db.query(FollowUp).filter(FollowUp.id == followup_id).first()
    if not followup:
        raise HTTPException(status_code=404, detail="Follow-up not found")

    response = db.query(Response).filter(Response.id == followup.response_id).first()
    if not response or response.assessment_id != assessment.id:
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
