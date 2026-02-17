from datetime import datetime

from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app import templates
from models import (
    get_db, Vendor, RemediationItem,
    VALID_REMEDIATION_STATUSES, REMEDIATION_STATUS_LABELS, REMEDIATION_STATUS_COLORS,
    REMEDIATION_STATUS_OPEN, REMEDIATION_STATUS_CLOSED, REMEDIATION_STATUS_VERIFIED,
    REMEDIATION_SOURCE_MANUAL,
    VALID_SEVERITIES,
)

router = APIRouter()


@router.get("/remediations/{remediation_id}", response_class=HTMLResponse)
async def remediation_detail(request: Request, remediation_id: int, db: Session = Depends(get_db)):
    item = db.query(RemediationItem).filter(RemediationItem.id == remediation_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Remediation item not found")

    vendor = db.query(Vendor).filter(Vendor.id == item.vendor_id).first()

    return templates.TemplateResponse("remediation_detail.html", {
        "request": request,
        "item": item,
        "vendor": vendor,
        "statuses": VALID_REMEDIATION_STATUSES,
        "status_labels": REMEDIATION_STATUS_LABELS,
        "status_colors": REMEDIATION_STATUS_COLORS,
        "severities": VALID_SEVERITIES,
    })


@router.post("/remediations/{remediation_id}")
async def update_remediation(
    remediation_id: int,
    status: str = Form(...),
    assigned_to: str = Form(""),
    due_date: str = Form(""),
    evidence_notes: str = Form(""),
    db: Session = Depends(get_db)
):
    item = db.query(RemediationItem).filter(RemediationItem.id == remediation_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Remediation item not found")

    if status in VALID_REMEDIATION_STATUSES:
        item.status = status
    item.assigned_to = assigned_to.strip() or None
    item.evidence_notes = evidence_notes.strip() or None

    if due_date:
        try:
            item.due_date = datetime.strptime(due_date, "%Y-%m-%d")
        except ValueError:
            pass

    if status in (REMEDIATION_STATUS_CLOSED, REMEDIATION_STATUS_VERIFIED):
        item.completed_date = datetime.utcnow()
    else:
        item.completed_date = None

    db.commit()

    return RedirectResponse(
        url=f"/remediations/{remediation_id}?message=Remediation updated&message_type=success",
        status_code=303
    )


@router.post("/vendors/{vendor_id}/remediations")
async def create_manual_remediation(
    vendor_id: int,
    title: str = Form(...),
    description: str = Form(""),
    category: str = Form(""),
    severity: str = Form("MEDIUM"),
    assigned_to: str = Form(""),
    due_date: str = Form(""),
    db: Session = Depends(get_db)
):
    vendor = db.query(Vendor).filter(Vendor.id == vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    item = RemediationItem(
        vendor_id=vendor_id,
        title=title.strip(),
        description=description.strip() or None,
        source=REMEDIATION_SOURCE_MANUAL,
        category=category.strip() or None,
        severity=severity if severity in VALID_SEVERITIES else "MEDIUM",
        status=REMEDIATION_STATUS_OPEN,
        assigned_to=assigned_to.strip() or None,
    )

    if due_date:
        try:
            item.due_date = datetime.strptime(due_date, "%Y-%m-%d")
        except ValueError:
            pass

    db.add(item)
    db.commit()

    return RedirectResponse(
        url=f"/vendors/{vendor_id}?message=Remediation item created&message_type=success",
        status_code=303
    )


@router.post("/remediations/{remediation_id}/delete")
async def delete_remediation(remediation_id: int, db: Session = Depends(get_db)):
    item = db.query(RemediationItem).filter(RemediationItem.id == remediation_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Remediation item not found")

    vendor_id = item.vendor_id
    db.delete(item)
    db.commit()

    return RedirectResponse(
        url=f"/vendors/{vendor_id}?message=Remediation item deleted&message_type=success",
        status_code=303
    )
