"""Vendor onboarding wizard — guided 4-step flow."""

from datetime import datetime, timedelta

from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from typing import Optional

from app import templates
from models import (
    get_db, Vendor, VendorContact, Assessment, AssessmentTemplate, TemplateQuestion,
    VENDOR_STATUS_ACTIVE,
    VALID_INDUSTRIES, VALID_SERVICE_TYPES, VALID_DATA_CLASSIFICATIONS,
    VALID_BUSINESS_CRITICALITIES, VALID_ACCESS_LEVELS,
    ACTIVITY_VENDOR_CREATED, ACTIVITY_ASSESSMENT_CREATED,
    ACTIVITY_ASSESSMENT_SENT, ACTIVITY_ONBOARDING_COMPLETE,
    NOTIF_ONBOARDING_COMPLETE,
)
from app.services.token import generate_unique_token
from app.services.cloning import clone_template_to_assessment
from app.services.lifecycle import transition_to_sent
from app.services.email_service import send_assessment_invitation
from app.services.tiering import compute_inherent_risk_tier, TIER_COLORS, TIER_LABELS
from app.services.activity_service import log_activity
from app.services.notification_service import create_notification

router = APIRouter()


@router.get("/onboarding", response_class=HTMLResponse)
async def onboarding_page(request: Request, db: Session = Depends(get_db)):
    """Render the onboarding wizard."""
    vendors = db.query(Vendor).filter(
        Vendor.status == VENDOR_STATUS_ACTIVE
    ).order_by(Vendor.name).all()

    tmpl_list = db.query(AssessmentTemplate).order_by(
        AssessmentTemplate.name
    ).all()

    return templates.TemplateResponse("onboarding_wizard.html", {
        "request": request,
        "vendors": vendors,
        "templates": tmpl_list,
        "industries": VALID_INDUSTRIES,
        "service_types": VALID_SERVICE_TYPES,
        "data_classifications": VALID_DATA_CLASSIFICATIONS,
        "business_criticalities": VALID_BUSINESS_CRITICALITIES,
        "access_levels": VALID_ACCESS_LEVELS,
        "tier_colors": TIER_COLORS,
        "tier_labels": TIER_LABELS,
    })


# ----- JSON API endpoints for wizard JavaScript -----

@router.get("/api/compute-tier")
async def api_compute_tier(
    data_classification: str = "",
    business_criticality: str = "",
    access_level: str = "",
):
    """Live tier computation for the wizard."""
    tier = compute_inherent_risk_tier(data_classification, business_criticality, access_level)
    return JSONResponse(content={
        "tier": tier,
        "color": TIER_COLORS.get(tier, "#6c757d"),
        "label": TIER_LABELS.get(tier, ""),
    })


@router.get("/api/templates-for-tier")
async def api_templates_for_tier(tier: str = "", db: Session = Depends(get_db)):
    """Return templates sorted by match to the given tier."""
    all_templates = db.query(AssessmentTemplate).order_by(
        AssessmentTemplate.name
    ).all()

    result = []
    for t in all_templates:
        q_count = db.query(TemplateQuestion).filter(
            TemplateQuestion.template_id == t.id
        ).count()
        result.append({
            "id": t.id,
            "name": t.name,
            "description": t.description or "",
            "suggested_tier": t.suggested_tier,
            "question_count": q_count,
            "recommended": t.suggested_tier == tier if tier else False,
        })

    # Sort: recommended first, then by name
    result.sort(key=lambda x: (not x["recommended"], x["name"]))
    return JSONResponse(content=result)


@router.get("/api/template-preview/{template_id}")
async def api_template_preview(template_id: int, db: Session = Depends(get_db)):
    """Return questions for a template, grouped by category."""
    questions = db.query(TemplateQuestion).filter(
        TemplateQuestion.template_id == template_id
    ).order_by(TemplateQuestion.order).all()

    categories = {}
    for q in questions:
        cat = q.category or "General"
        categories.setdefault(cat, []).append(q.question_text)

    return JSONResponse(content={
        "total": len(questions),
        "categories": categories,
    })


@router.get("/api/vendor-contacts/{vendor_id}")
async def api_vendor_contacts(vendor_id: int, db: Session = Depends(get_db)):
    """Return contacts for an existing vendor."""
    contacts = db.query(VendorContact).filter(
        VendorContact.vendor_id == vendor_id,
        VendorContact.email.isnot(None),
        VendorContact.email != "",
    ).order_by(VendorContact.name).all()

    return JSONResponse(content=[
        {
            "id": c.id,
            "name": c.name,
            "email": c.email,
            "role": c.role or "",
        }
        for c in contacts
    ])


# ----- Launch endpoint -----

@router.post("/onboarding/launch")
async def onboarding_launch(
    request: Request,
    vendor_mode: str = Form("new"),
    existing_vendor_id: str = Form(""),
    vendor_name: str = Form(""),
    industry: str = Form(""),
    service_type: str = Form(""),
    data_classification: str = Form(""),
    business_criticality: str = Form(""),
    access_level: str = Form(""),
    template_id: int = Form(...),
    assessment_title: str = Form(""),
    contact_email: str = Form(...),
    contact_name: str = Form(""),
    custom_message: str = Form(""),
    expiry_days: int = Form(30),
    first_reminder_days: int = Form(3),
    reminder_frequency_days: int = Form(7),
    max_reminders: int = Form(3),
    db: Session = Depends(get_db),
):
    """Execute the full onboarding workflow in one request."""

    # 1. Create or select vendor
    parsed_vendor_id = int(existing_vendor_id) if existing_vendor_id.strip().isdigit() else None
    if vendor_mode == "existing" and parsed_vendor_id:
        vendor = db.query(Vendor).filter(Vendor.id == parsed_vendor_id).first()
        if not vendor:
            raise HTTPException(status_code=404, detail="Vendor not found")
    else:
        if not vendor_name.strip():
            raise HTTPException(status_code=400, detail="Vendor name is required")

        tier = compute_inherent_risk_tier(data_classification, business_criticality, access_level)
        vendor = Vendor(
            name=vendor_name.strip(),
            status=VENDOR_STATUS_ACTIVE,
            industry=industry.strip() or None,
            service_type=service_type.strip() or None,
            data_classification=data_classification.strip() or None,
            business_criticality=business_criticality.strip() or None,
            access_level=access_level.strip() or None,
            inherent_risk_tier=tier,
        )
        db.add(vendor)
        db.flush()
        log_activity(db, vendor.id, ACTIVITY_VENDOR_CREATED,
                     f"Vendor '{vendor.name}' created via onboarding wizard")

    # 2. Create assessment from template
    tmpl = db.query(AssessmentTemplate).filter(
        AssessmentTemplate.id == template_id
    ).first()
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")

    token = generate_unique_token(db)
    title = assessment_title.strip() or f"Security Assessment {vendor.name}"

    assessment = Assessment(
        company_name=vendor.name,
        title=title,
        token=token,
        vendor_id=vendor.id,
        template_id=tmpl.id,
    )
    db.add(assessment)
    db.flush()

    clone_template_to_assessment(db, tmpl.id, assessment.id)
    log_activity(db, vendor.id, ACTIVITY_ASSESSMENT_CREATED,
                 f"Assessment '{title}' created from template '{tmpl.name}'",
                 assessment_id=assessment.id)

    # 3. Send email
    base_url = str(request.base_url).rstrip("/")
    assessment_url = f"{base_url}/vendor/{assessment.token}"
    expires_at = datetime.utcnow() + timedelta(days=expiry_days) if expiry_days > 0 else None

    send_assessment_invitation(
        to_email=contact_email.strip(),
        to_name=contact_name.strip() or vendor.name,
        vendor_name=vendor.name,
        assessment_title=title,
        assessment_url=assessment_url,
        custom_message=custom_message.strip() or None,
        expires_at=expires_at,
    )

    assessment.sent_to_email = contact_email.strip()
    assessment.sent_at = datetime.utcnow()
    if expires_at:
        assessment.expires_at = expires_at
    assessment.first_reminder_days = first_reminder_days
    assessment.reminder_frequency_days = reminder_frequency_days
    assessment.max_reminders = max_reminders
    transition_to_sent(db, assessment)

    log_activity(db, vendor.id, ACTIVITY_ASSESSMENT_SENT,
                 f"Assessment '{title}' sent to {contact_email.strip()}",
                 assessment_id=assessment.id)

    # 4. Log onboarding complete + notification
    log_activity(db, vendor.id, ACTIVITY_ONBOARDING_COMPLETE,
                 f"Onboarding complete — assessment sent to {contact_email.strip()}",
                 assessment_id=assessment.id)

    create_notification(db, NOTIF_ONBOARDING_COMPLETE,
                        f"Onboarding complete for {vendor.name} — assessment sent",
                        link=f"/vendors/{vendor.id}",
                        vendor_id=vendor.id,
                        assessment_id=assessment.id)

    db.commit()

    # 5. Redirect to vendor profile
    return RedirectResponse(
        url=f"/vendors/{vendor.id}?message=Onboarding+complete!+Assessment+sent+to+{contact_email.strip()}&message_type=success",
        status_code=303,
    )
