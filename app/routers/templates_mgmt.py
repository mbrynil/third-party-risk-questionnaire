from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app import templates
from models import get_db, Assessment, AssessmentTemplate
from app.services.token import generate_unique_token
from app.services.cloning import clone_assessment_to_template, clone_template_to_assessment
from app.services.vendor_service import find_or_create_vendor

router = APIRouter()


@router.get("/templates", response_class=HTMLResponse)
async def view_templates(request: Request, db: Session = Depends(get_db)):
    templates_list = db.query(AssessmentTemplate).order_by(
        AssessmentTemplate.created_at.desc()
    ).all()
    return templates.TemplateResponse("templates_list.html", {
        "request": request,
        "templates": templates_list
    })


@router.post("/questionnaires/{assessment_id}/save-as-template")
async def save_as_template(
    request: Request,
    assessment_id: int,
    template_name: str = Form(...),
    template_description: str = Form(""),
    db: Session = Depends(get_db)
):
    source = db.query(Assessment).filter(Assessment.id == assessment_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Assessment not found")

    token = generate_unique_token(db)

    new_template = AssessmentTemplate(
        name=template_name.strip(),
        description=template_description.strip() if template_description else None,
        source_title=source.title,
        source_company=source.company_name,
        token=token,
    )
    db.add(new_template)
    db.flush()

    clone_assessment_to_template(db, source.id, new_template.id)

    db.commit()

    return RedirectResponse(url="/templates?saved=1", status_code=303)


@router.post("/templates/{template_id}/create-questionnaire")
async def create_from_template(
    request: Request,
    template_id: int,
    company_name: str = Form(...),
    title: str = Form(...),
    db: Session = Depends(get_db)
):
    source = db.query(AssessmentTemplate).filter(
        AssessmentTemplate.id == template_id
    ).first()
    if not source:
        raise HTTPException(status_code=404, detail="Template not found")

    normalized_company_name = company_name.strip()
    normalized_title = title.strip()

    token = generate_unique_token(db)
    vendor = find_or_create_vendor(db, normalized_company_name)

    new_assessment = Assessment(
        company_name=normalized_company_name,
        title=normalized_title,
        token=token,
        vendor_id=vendor.id,
        template_id=source.id,
    )
    db.add(new_assessment)
    db.flush()

    clone_template_to_assessment(db, source.id, new_assessment.id)

    db.commit()

    return RedirectResponse(url=f"/questionnaire/{new_assessment.id}/edit?from_template=1", status_code=303)


@router.post("/templates/{template_id}/delete")
async def delete_template(template_id: int, db: Session = Depends(get_db)):
    template = db.query(AssessmentTemplate).filter(
        AssessmentTemplate.id == template_id
    ).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    db.delete(template)
    db.commit()

    return RedirectResponse(url="/templates?deleted=1", status_code=303)
