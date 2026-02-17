import os
from datetime import datetime

from fastapi import APIRouter, Request, Form, Depends, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from sqlalchemy.orm import Session
from typing import Optional

from app import templates
from models import (
    get_db, Assessment, AssessmentTemplate, Vendor, AssessmentDecision,
    VendorContact, VendorDocument,
    VENDOR_STATUS_ACTIVE, VALID_VENDOR_STATUSES,
    VALID_INDUSTRIES, VALID_SERVICE_TYPES, VALID_DATA_CLASSIFICATIONS,
    VALID_BUSINESS_CRITICALITIES, VALID_ACCESS_LEVELS, VALID_INHERENT_RISK_TIERS,
    VALID_CONTACT_ROLES, VALID_DOCUMENT_TYPES, DOCUMENT_TYPE_LABELS,
    REMEDIATION_STATUS_LABELS, REMEDIATION_STATUS_COLORS,
    VALID_SEVERITIES,
)
from app.services.token import generate_unique_token
from app.services.cloning import clone_template_to_assessment
from app.services.tiering import compute_inherent_risk_tier, get_effective_tier, TIER_COLORS, TIER_LABELS
from app.services.vendor_document_service import validate_document_upload, store_vendor_document
from app.services.remediation_service import get_vendor_remediations, get_remediation_stats
from app.services.reassessment_service import create_reassessment

router = APIRouter()


def _classification_context():
    """Return constants needed by vendor edit templates."""
    return {
        "industries": VALID_INDUSTRIES,
        "service_types": VALID_SERVICE_TYPES,
        "data_classifications": VALID_DATA_CLASSIFICATIONS,
        "business_criticalities": VALID_BUSINESS_CRITICALITIES,
        "access_levels": VALID_ACCESS_LEVELS,
        "inherent_risk_tiers": VALID_INHERENT_RISK_TIERS,
    }


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
        "vendor": None,
        **_classification_context(),
    })


@router.post("/vendors/new")
async def create_vendor(
    request: Request,
    name: str = Form(...),
    primary_contact_name: str = Form(""),
    primary_contact_email: str = Form(""),
    notes: str = Form(""),
    industry: str = Form(""),
    website: str = Form(""),
    headquarters: str = Form(""),
    service_type: str = Form(""),
    data_classification: str = Form(""),
    business_criticality: str = Form(""),
    access_level: str = Form(""),
    contract_start_date: str = Form(""),
    contract_end_date: str = Form(""),
    contract_value: str = Form(""),
    auto_renewal: str = Form(""),
    db: Session = Depends(get_db)
):
    if not name.strip():
        return templates.TemplateResponse("vendor_edit.html", {
            "request": request,
            "vendor": None,
            "error": "Vendor name is required.",
            **_classification_context(),
        })

    tier = compute_inherent_risk_tier(data_classification, business_criticality, access_level)

    vendor = Vendor(
        name=name.strip(),
        primary_contact_name=primary_contact_name.strip() or None,
        primary_contact_email=primary_contact_email.strip() or None,
        notes=notes.strip() or None,
        status=VENDOR_STATUS_ACTIVE,
        industry=industry.strip() or None,
        website=website.strip() or None,
        headquarters=headquarters.strip() or None,
        service_type=service_type.strip() or None,
        data_classification=data_classification.strip() or None,
        business_criticality=business_criticality.strip() or None,
        access_level=access_level.strip() or None,
        inherent_risk_tier=tier,
        contract_value=contract_value.strip() or None,
        auto_renewal=auto_renewal == "on",
    )

    if contract_start_date:
        try:
            vendor.contract_start_date = datetime.strptime(contract_start_date, "%Y-%m-%d")
        except ValueError:
            pass
    if contract_end_date:
        try:
            vendor.contract_end_date = datetime.strptime(contract_end_date, "%Y-%m-%d")
        except ValueError:
            pass

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

    effective_tier = get_effective_tier(vendor)
    remediations = get_vendor_remediations(db, vendor_id)
    remediation_stats = get_remediation_stats(db, vendor_id)

    return templates.TemplateResponse("vendor_profile.html", {
        "request": request,
        "vendor": vendor,
        "assessments": assessments,
        "templates": templates_list,
        "decisions": decisions,
        "effective_tier": effective_tier,
        "tier_colors": TIER_COLORS,
        "tier_labels": TIER_LABELS,
        "inherent_risk_tiers": VALID_INHERENT_RISK_TIERS,
        "contact_roles": VALID_CONTACT_ROLES,
        "document_types": VALID_DOCUMENT_TYPES,
        "document_type_labels": DOCUMENT_TYPE_LABELS,
        "remediations": remediations,
        "remediation_stats": remediation_stats,
        "remediation_status_labels": REMEDIATION_STATUS_LABELS,
        "remediation_status_colors": REMEDIATION_STATUS_COLORS,
    })


@router.get("/vendors/{vendor_id}/edit", response_class=HTMLResponse)
async def edit_vendor_page(request: Request, vendor_id: int, db: Session = Depends(get_db)):
    vendor = db.query(Vendor).filter(Vendor.id == vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    return templates.TemplateResponse("vendor_edit.html", {
        "request": request,
        "vendor": vendor,
        **_classification_context(),
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
    industry: str = Form(""),
    website: str = Form(""),
    headquarters: str = Form(""),
    service_type: str = Form(""),
    data_classification: str = Form(""),
    business_criticality: str = Form(""),
    access_level: str = Form(""),
    contract_start_date: str = Form(""),
    contract_end_date: str = Form(""),
    contract_value: str = Form(""),
    auto_renewal: str = Form(""),
    db: Session = Depends(get_db)
):
    vendor = db.query(Vendor).filter(Vendor.id == vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    if not name.strip():
        return templates.TemplateResponse("vendor_edit.html", {
            "request": request,
            "vendor": vendor,
            "error": "Vendor name is required.",
            **_classification_context(),
        })

    vendor.name = name.strip()
    vendor.primary_contact_name = primary_contact_name.strip() or None
    vendor.primary_contact_email = primary_contact_email.strip() or None
    vendor.notes = notes.strip() or None
    if status in VALID_VENDOR_STATUSES:
        vendor.status = status

    vendor.industry = industry.strip() or None
    vendor.website = website.strip() or None
    vendor.headquarters = headquarters.strip() or None
    vendor.service_type = service_type.strip() or None
    vendor.data_classification = data_classification.strip() or None
    vendor.business_criticality = business_criticality.strip() or None
    vendor.access_level = access_level.strip() or None
    vendor.contract_value = contract_value.strip() or None
    vendor.auto_renewal = auto_renewal == "on"

    if contract_start_date:
        try:
            vendor.contract_start_date = datetime.strptime(contract_start_date, "%Y-%m-%d")
        except ValueError:
            pass
    else:
        vendor.contract_start_date = None

    if contract_end_date:
        try:
            vendor.contract_end_date = datetime.strptime(contract_end_date, "%Y-%m-%d")
        except ValueError:
            pass
    else:
        vendor.contract_end_date = None

    # Recompute inherent risk tier
    vendor.inherent_risk_tier = compute_inherent_risk_tier(
        vendor.data_classification, vendor.business_criticality, vendor.access_level
    )

    db.commit()

    return RedirectResponse(url=f"/vendors/{vendor_id}?updated=1", status_code=303)


# ==================== CONTACTS ====================

@router.post("/vendors/{vendor_id}/contacts")
async def add_contact(
    vendor_id: int,
    contact_name: str = Form(...),
    contact_email: str = Form(""),
    contact_role: str = Form(""),
    contact_phone: str = Form(""),
    db: Session = Depends(get_db)
):
    vendor = db.query(Vendor).filter(Vendor.id == vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    contact = VendorContact(
        vendor_id=vendor_id,
        name=contact_name.strip(),
        email=contact_email.strip() or None,
        role=contact_role.strip() or None,
        phone=contact_phone.strip() or None,
    )
    db.add(contact)
    db.commit()

    return RedirectResponse(url=f"/vendors/{vendor_id}?contact_added=1", status_code=303)


@router.post("/vendors/{vendor_id}/contacts/{contact_id}/delete")
async def delete_contact(vendor_id: int, contact_id: int, db: Session = Depends(get_db)):
    contact = db.query(VendorContact).filter(
        VendorContact.id == contact_id,
        VendorContact.vendor_id == vendor_id
    ).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    db.delete(contact)
    db.commit()

    return RedirectResponse(url=f"/vendors/{vendor_id}?contact_deleted=1", status_code=303)


# ==================== DOCUMENTS ====================

@router.post("/vendors/{vendor_id}/documents")
async def upload_document(
    vendor_id: int,
    document_type: str = Form(...),
    document_title: str = Form(...),
    expiry_date: str = Form(""),
    document_notes: str = Form(""),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    vendor = db.query(Vendor).filter(Vendor.id == vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    file_content = await file.read()
    error = validate_document_upload(file.filename, len(file_content))
    if error:
        return RedirectResponse(
            url=f"/vendors/{vendor_id}?message={error}&message_type=danger",
            status_code=303
        )

    safe_name, stored_filename, stored_path = store_vendor_document(
        file_content, file.filename, vendor_id
    )

    parsed_expiry = None
    if expiry_date:
        try:
            parsed_expiry = datetime.strptime(expiry_date, "%Y-%m-%d")
        except ValueError:
            pass

    doc = VendorDocument(
        vendor_id=vendor_id,
        document_type=document_type,
        title=document_title.strip(),
        original_filename=safe_name,
        stored_filename=stored_filename,
        stored_path=stored_path,
        content_type=file.content_type,
        size_bytes=len(file_content),
        expiry_date=parsed_expiry,
        notes=document_notes.strip() or None,
    )
    db.add(doc)
    db.commit()

    return RedirectResponse(url=f"/vendors/{vendor_id}?document_uploaded=1", status_code=303)


@router.get("/vendors/{vendor_id}/documents/{document_id}/download")
async def download_document(vendor_id: int, document_id: int, db: Session = Depends(get_db)):
    doc = db.query(VendorDocument).filter(
        VendorDocument.id == document_id,
        VendorDocument.vendor_id == vendor_id
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if not os.path.exists(doc.stored_path):
        raise HTTPException(status_code=404, detail="File not found on disk")

    return FileResponse(
        path=doc.stored_path,
        filename=doc.original_filename,
        media_type=doc.content_type or "application/octet-stream",
    )


@router.post("/vendors/{vendor_id}/documents/{document_id}/delete")
async def delete_document(vendor_id: int, document_id: int, db: Session = Depends(get_db)):
    doc = db.query(VendorDocument).filter(
        VendorDocument.id == document_id,
        VendorDocument.vendor_id == vendor_id
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if os.path.exists(doc.stored_path):
        os.remove(doc.stored_path)

    db.delete(doc)
    db.commit()

    return RedirectResponse(url=f"/vendors/{vendor_id}?document_deleted=1", status_code=303)


# ==================== TIER OVERRIDE ====================

@router.post("/vendors/{vendor_id}/tier-override")
async def set_tier_override(
    vendor_id: int,
    tier_override: str = Form(""),
    tier_notes: str = Form(""),
    db: Session = Depends(get_db)
):
    vendor = db.query(Vendor).filter(Vendor.id == vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    vendor.tier_override = tier_override.strip() if tier_override.strip() in VALID_INHERENT_RISK_TIERS else None
    vendor.tier_notes = tier_notes.strip() or None
    db.commit()

    return RedirectResponse(url=f"/vendors/{vendor_id}?tier_updated=1", status_code=303)


# ==================== REASSESSMENT ====================

@router.post("/vendors/{vendor_id}/reassess")
async def initiate_reassessment(
    vendor_id: int,
    previous_assessment_id: int = Form(...),
    db: Session = Depends(get_db)
):
    vendor = db.query(Vendor).filter(Vendor.id == vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    new_assessment = create_reassessment(db, vendor_id, previous_assessment_id)
    if not new_assessment:
        return RedirectResponse(
            url=f"/vendors/{vendor_id}?message=Previous assessment not found&message_type=danger",
            status_code=303
        )

    db.commit()

    return RedirectResponse(
        url=f"/questionnaire/{new_assessment.id}/edit?reassessment=1",
        status_code=303
    )


# ==================== ASSESSMENT CREATION ====================

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
