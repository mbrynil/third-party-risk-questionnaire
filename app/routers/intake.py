from datetime import datetime

from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app import templates
from models import (
    get_db, User, VendorIntakeRequest,
    VALID_INTAKE_URGENCIES, VALID_INTAKE_STATUSES,
    INTAKE_STATUS_PENDING,
    NOTIF_INTAKE_SUBMITTED, NOTIF_INTAKE_APPROVED, NOTIF_INTAKE_REJECTED,
)
from app.services.intake_service import (
    create_intake_request, approve_intake, reject_intake,
    get_intake_requests, get_pending_intake_count,
)
from app.services.notification_service import create_notification
from app.services.auth_service import require_login, require_role

router = APIRouter()


@router.get("/intake/new", response_class=HTMLResponse)
async def intake_form_page(request: Request, db: Session = Depends(get_db),
                           current_user: User = Depends(require_login)):
    return templates.TemplateResponse("intake_form.html", {
        "request": request,
        "urgencies": VALID_INTAKE_URGENCIES,
    })


@router.post("/intake")
async def submit_intake(
    request: Request,
    vendor_name: str = Form(...),
    business_justification: str = Form(""),
    department: str = Form(""),
    service_description: str = Form(""),
    data_types_shared: str = Form(""),
    estimated_contract_value: str = Form(""),
    urgency: str = Form("MEDIUM"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_login),
):
    if not vendor_name.strip():
        return templates.TemplateResponse("intake_form.html", {
            "request": request,
            "urgencies": VALID_INTAKE_URGENCIES,
            "error": "Vendor name is required.",
        })

    req = create_intake_request(
        db, current_user.id, vendor_name.strip(),
        business_justification=business_justification.strip() or None,
        department=department.strip() or None,
        service_description=service_description.strip() or None,
        data_types_shared=data_types_shared.strip() or None,
        estimated_contract_value=estimated_contract_value.strip() or None,
        urgency=urgency if urgency in VALID_INTAKE_URGENCIES else "MEDIUM",
    )
    create_notification(db, NOTIF_INTAKE_SUBMITTED,
                        f"New vendor intake request: {vendor_name.strip()} by {current_user.display_name}",
                        link="/intake")
    db.commit()

    return RedirectResponse(
        url="/intake?message=Intake request submitted successfully&message_type=success",
        status_code=303,
    )


@router.get("/intake", response_class=HTMLResponse)
async def intake_list(request: Request, db: Session = Depends(get_db),
                      current_user: User = Depends(require_login)):
    requests_list = get_intake_requests(db, user_id=current_user.id, role=current_user.role)
    pending_count = get_pending_intake_count(db)
    return templates.TemplateResponse("intake_list.html", {
        "request": request,
        "intake_requests": requests_list,
        "pending_count": pending_count,
        "statuses": VALID_INTAKE_STATUSES,
    })


@router.get("/intake/{intake_id}", response_class=HTMLResponse)
async def intake_detail(request: Request, intake_id: int, db: Session = Depends(get_db),
                        current_user: User = Depends(require_login)):
    req = db.query(VendorIntakeRequest).filter(VendorIntakeRequest.id == intake_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Intake request not found")
    if current_user.role == "viewer" and req.requested_by_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    return templates.TemplateResponse("intake_detail.html", {
        "request": request,
        "intake": req,
    })


@router.post("/intake/{intake_id}/approve")
async def approve_intake_route(
    intake_id: int,
    review_notes: str = Form(""),
    create_vendor_flag: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "analyst")),
):
    req, vendor = approve_intake(
        db, intake_id, current_user.id,
        review_notes=review_notes.strip() or None,
        create_vendor=(create_vendor_flag == "on"),
    )
    if req:
        create_notification(db, NOTIF_INTAKE_APPROVED,
                            f"Your intake request for '{req.vendor_name}' was approved",
                            link=f"/intake/{intake_id}")
        db.commit()
        if vendor:
            return RedirectResponse(
                url=f"/onboarding?vendor_id={vendor.id}&message=Intake approved, vendor created&message_type=success",
                status_code=303,
            )
    return RedirectResponse(
        url="/intake?message=Intake request approved&message_type=success",
        status_code=303,
    )


@router.post("/intake/{intake_id}/reject")
async def reject_intake_route(
    intake_id: int,
    review_notes: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "analyst")),
):
    req = reject_intake(db, intake_id, current_user.id,
                        review_notes=review_notes.strip() or None)
    if req:
        create_notification(db, NOTIF_INTAKE_REJECTED,
                            f"Your intake request for '{req.vendor_name}' was rejected",
                            link=f"/intake/{intake_id}")
        db.commit()
    return RedirectResponse(
        url="/intake?message=Intake request rejected&message_type=info",
        status_code=303,
    )
