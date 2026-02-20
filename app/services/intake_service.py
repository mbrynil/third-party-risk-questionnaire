from datetime import datetime
from sqlalchemy.orm import Session
from models import (
    VendorIntakeRequest, Vendor, VENDOR_STATUS_ACTIVE,
    INTAKE_STATUS_PENDING, INTAKE_STATUS_APPROVED,
    INTAKE_STATUS_REJECTED, INTAKE_STATUS_CONVERTED,
)


def create_intake_request(db: Session, requested_by_id: int, vendor_name: str,
                          business_justification: str = None, department: str = None,
                          service_description: str = None, data_types_shared: str = None,
                          estimated_contract_value: str = None, urgency: str = "MEDIUM") -> VendorIntakeRequest:
    req = VendorIntakeRequest(
        requested_by_id=requested_by_id,
        vendor_name=vendor_name,
        business_justification=business_justification,
        department=department,
        service_description=service_description,
        data_types_shared=data_types_shared,
        estimated_contract_value=estimated_contract_value,
        urgency=urgency,
        status=INTAKE_STATUS_PENDING,
    )
    db.add(req)
    db.flush()
    return req


def approve_intake(db: Session, intake_id: int, reviewed_by_id: int,
                   review_notes: str = None, create_vendor: bool = False) -> tuple:
    req = db.query(VendorIntakeRequest).filter(VendorIntakeRequest.id == intake_id).first()
    if not req or req.status != INTAKE_STATUS_PENDING:
        return req, None

    req.status = INTAKE_STATUS_APPROVED
    req.reviewed_by_id = reviewed_by_id
    req.review_notes = review_notes
    req.updated_at = datetime.utcnow()

    vendor = None
    if create_vendor:
        vendor = Vendor(name=req.vendor_name, status=VENDOR_STATUS_ACTIVE)
        db.add(vendor)
        db.flush()
        req.vendor_id = vendor.id
        req.status = INTAKE_STATUS_CONVERTED

    return req, vendor


def reject_intake(db: Session, intake_id: int, reviewed_by_id: int,
                  review_notes: str = None) -> VendorIntakeRequest:
    req = db.query(VendorIntakeRequest).filter(VendorIntakeRequest.id == intake_id).first()
    if not req or req.status != INTAKE_STATUS_PENDING:
        return req

    req.status = INTAKE_STATUS_REJECTED
    req.reviewed_by_id = reviewed_by_id
    req.review_notes = review_notes
    req.updated_at = datetime.utcnow()
    return req


def get_intake_requests(db: Session, user_id: int = None, role: str = None) -> list[VendorIntakeRequest]:
    query = db.query(VendorIntakeRequest)
    if role == "viewer" and user_id:
        query = query.filter(VendorIntakeRequest.requested_by_id == user_id)
    return query.order_by(VendorIntakeRequest.created_at.desc()).all()


def get_pending_intake_count(db: Session) -> int:
    return db.query(VendorIntakeRequest).filter(
        VendorIntakeRequest.status == INTAKE_STATUS_PENDING
    ).count()
