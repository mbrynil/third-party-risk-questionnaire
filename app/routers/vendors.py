from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from typing import Optional

from app import templates
from models import (
    get_db, Assessment, AssessmentTemplate, Vendor, AssessmentDecision,
    VENDOR_STATUS_ACTIVE, VALID_VENDOR_STATUSES,
)
from app.services.token import generate_unique_token
from app.services.cloning import clone_template_to_assessment

router = APIRouter()


@router.get("/vendors", response_class=HTMLResponse)
async def vendors_list(request: Request, db: Session = Depends(get_db)):
    vendors = db.query(Vendor).order_by(Vendor.name).all()
    return templates.TemplateResponse("vendors.html", {
        "request": request,
        "vendors": vendors
    })


@router.get("/vendors/new", response_class=HTMLResponse)
async def new_vendor_page(request: Request):
    return templates.TemplateResponse("vendor_edit.html", {
        "request": request,
        "vendor": None
    })


@router.post("/vendors/new")
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


@router.get("/vendors/{vendor_id}", response_class=HTMLResponse)
async def vendor_profile(request: Request, vendor_id: int, db: Session = Depends(get_db)):
    vendor = db.query(Vendor).filter(Vendor.id == vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    assessments = db.query(Assessment).filter(
        Assessment.vendor_id == vendor_id
    ).order_by(Assessment.created_at.desc()).all()

    templates_list = db.query(AssessmentTemplate).order_by(
        AssessmentTemplate.name
    ).all()

    assessment_ids = [a.id for a in assessments]
    assessment_decisions = db.query(AssessmentDecision).filter(
        AssessmentDecision.assessment_id.in_(assessment_ids)
    ).all() if assessment_ids else []
    decisions = {d.assessment_id: d for d in assessment_decisions}

    return templates.TemplateResponse("vendor_profile.html", {
        "request": request,
        "vendor": vendor,
        "assessments": assessments,
        "templates": templates_list,
        "decisions": decisions
    })


@router.get("/vendors/{vendor_id}/edit", response_class=HTMLResponse)
async def edit_vendor_page(request: Request, vendor_id: int, db: Session = Depends(get_db)):
    vendor = db.query(Vendor).filter(Vendor.id == vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    return templates.TemplateResponse("vendor_edit.html", {
        "request": request,
        "vendor": vendor
    })


@router.post("/vendors/{vendor_id}/edit")
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


@router.post("/vendors/{vendor_id}/create-assessment")
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

    token = generate_unique_token(db)

    if source == "template" and template_id:
        tmpl = db.query(AssessmentTemplate).filter(
            AssessmentTemplate.id == template_id
        ).first()
        if not tmpl:
            raise HTTPException(status_code=404, detail="Template not found")

        new_assessment = Assessment(
            company_name=vendor.name,
            title=title.strip(),
            token=token,
            vendor_id=vendor.id,
            template_id=tmpl.id,
        )
        db.add(new_assessment)
        db.flush()

        clone_template_to_assessment(db, tmpl.id, new_assessment.id)

        db.commit()
        return RedirectResponse(url=f"/questionnaire/{new_assessment.id}/edit?from_template=1", status_code=303)

    else:
        new_assessment = Assessment(
            company_name=vendor.name,
            title=title.strip(),
            token=token,
            vendor_id=vendor.id,
        )
        db.add(new_assessment)
        db.commit()

        return RedirectResponse(url=f"/create?vendor_id={vendor.id}&questionnaire_id={new_assessment.id}", status_code=303)
