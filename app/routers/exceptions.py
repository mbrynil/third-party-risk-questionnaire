from datetime import datetime

from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app import templates
from models import (
    get_db, User, Vendor, RiskException,
    EXCEPTION_STATUS_PENDING, EXCEPTION_STATUS_APPROVED, EXCEPTION_STATUS_REJECTED,
    VALID_EXCEPTION_STATUSES,
    ACTIVITY_EXCEPTION_CREATED, ACTIVITY_EXCEPTION_APPROVED,
    NOTIF_EXCEPTION_REQUESTED, NOTIF_EXCEPTION_APPROVED,
)
from app.services.exception_service import (
    create_exception, approve_exception, reject_exception,
    get_vendor_exceptions, get_pending_exceptions,
)
from app.services.activity_service import log_activity
from app.services.notification_service import create_notification
from app.services.auth_service import require_login, require_role
from app.services.audit_service import log_audit
from models import AUDIT_ACTION_STATUS_CHANGE, AUDIT_ENTITY_EXCEPTION

router = APIRouter()


@router.get("/exceptions", response_class=HTMLResponse)
async def exceptions_list(request: Request, db: Session = Depends(get_db),
                          current_user: User = Depends(require_role("admin"))):
    pending = get_pending_exceptions(db)
    all_exceptions = db.query(RiskException).order_by(RiskException.created_at.desc()).all()
    return templates.TemplateResponse("exceptions_list.html", {
        "request": request,
        "pending": pending,
        "all_exceptions": all_exceptions,
        "statuses": VALID_EXCEPTION_STATUSES,
    })


@router.get("/vendors/{vendor_id}/exceptions", response_class=HTMLResponse)
async def vendor_exceptions(request: Request, vendor_id: int,
                            db: Session = Depends(get_db),
                            current_user: User = Depends(require_login)):
    vendor = db.query(Vendor).filter(Vendor.id == vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")
    exceptions = get_vendor_exceptions(db, vendor_id)
    return templates.TemplateResponse("exceptions_list.html", {
        "request": request,
        "vendor": vendor,
        "pending": [e for e in exceptions if e.status == EXCEPTION_STATUS_PENDING],
        "all_exceptions": exceptions,
        "statuses": VALID_EXCEPTION_STATUSES,
    })


@router.post("/vendors/{vendor_id}/exceptions")
async def create_vendor_exception(
    request: Request,
    vendor_id: int,
    title: str = Form(...),
    description: str = Form(""),
    risk_accepted: str = Form(""),
    justification: str = Form(""),
    expires_at: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "analyst")),
):
    vendor = db.query(Vendor).filter(Vendor.id == vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    parsed_expires = None
    if expires_at:
        try:
            parsed_expires = datetime.strptime(expires_at, "%Y-%m-%d")
        except ValueError:
            pass

    exc = create_exception(
        db, vendor_id, title.strip(), description.strip(),
        risk_accepted.strip(), justification.strip(),
        created_by_id=current_user.id,
        expires_at=parsed_expires,
    )
    log_activity(db, vendor_id, ACTIVITY_EXCEPTION_CREATED,
                 f"Exception requested: {title.strip()}", user_id=current_user.id)
    create_notification(db, NOTIF_EXCEPTION_REQUESTED,
                        f"Exception requested for {vendor.name}: {title.strip()}",
                        link=f"/exceptions", vendor_id=vendor_id)
    db.commit()

    return RedirectResponse(
        url=f"/vendors/{vendor_id}?message=Exception request created&message_type=success",
        status_code=303,
    )


@router.post("/exceptions/{exception_id}/approve")
async def approve_exception_route(
    exception_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    exc = approve_exception(db, exception_id, current_user.id)
    if exc:
        log_activity(db, exc.vendor_id, ACTIVITY_EXCEPTION_APPROVED,
                     f"Exception approved: {exc.title}", user_id=current_user.id)
        log_audit(db, AUDIT_ACTION_STATUS_CHANGE, AUDIT_ENTITY_EXCEPTION,
                  entity_id=exc.id, entity_label=exc.title[:100],
                  old_value={"status": "PENDING"},
                  new_value={"status": "APPROVED"},
                  description=f"Exception approved: {exc.title}",
                  actor_user=current_user,
                  ip_address=request.client.host if request.client else None)
        create_notification(db, NOTIF_EXCEPTION_APPROVED,
                            f"Exception approved: {exc.title}",
                            link=f"/vendors/{exc.vendor_id}", vendor_id=exc.vendor_id)
        db.commit()
    return RedirectResponse(url="/exceptions?message=Exception approved&message_type=success", status_code=303)


@router.post("/exceptions/{exception_id}/reject")
async def reject_exception_route(
    exception_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    exc = reject_exception(db, exception_id, current_user.id)
    if exc:
        log_audit(db, AUDIT_ACTION_STATUS_CHANGE, AUDIT_ENTITY_EXCEPTION,
                  entity_id=exc.id, entity_label=exc.title[:100],
                  old_value={"status": "PENDING"},
                  new_value={"status": "REJECTED"},
                  description=f"Exception rejected: {exc.title}",
                  actor_user=current_user,
                  ip_address=request.client.host if request.client else None)
        db.commit()
    return RedirectResponse(url="/exceptions?message=Exception rejected&message_type=info", status_code=303)
