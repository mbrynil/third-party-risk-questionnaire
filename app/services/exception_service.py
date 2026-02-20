from datetime import datetime
from sqlalchemy.orm import Session
from models import RiskException, EXCEPTION_STATUS_PENDING, EXCEPTION_STATUS_APPROVED, EXCEPTION_STATUS_REJECTED, EXCEPTION_STATUS_EXPIRED


def create_exception(db: Session, vendor_id: int, title: str, description: str,
                     risk_accepted: str, justification: str, created_by_id: int,
                     assessment_id: int = None, decision_id: int = None,
                     expires_at: datetime = None) -> RiskException:
    exc = RiskException(
        vendor_id=vendor_id,
        assessment_id=assessment_id,
        decision_id=decision_id,
        title=title,
        description=description,
        risk_accepted=risk_accepted,
        justification=justification,
        status=EXCEPTION_STATUS_PENDING,
        expires_at=expires_at,
        created_by_id=created_by_id,
    )
    db.add(exc)
    db.flush()
    return exc


def approve_exception(db: Session, exception_id: int, approved_by_id: int, notes: str = None) -> RiskException:
    exc = db.query(RiskException).filter(RiskException.id == exception_id).first()
    if exc and exc.status == EXCEPTION_STATUS_PENDING:
        exc.status = EXCEPTION_STATUS_APPROVED
        exc.approved_by_id = approved_by_id
        exc.approval_notes = notes  # stored in description or we just update status
        exc.updated_at = datetime.utcnow()
    return exc


def reject_exception(db: Session, exception_id: int, approved_by_id: int, notes: str = None) -> RiskException:
    exc = db.query(RiskException).filter(RiskException.id == exception_id).first()
    if exc and exc.status == EXCEPTION_STATUS_PENDING:
        exc.status = EXCEPTION_STATUS_REJECTED
        exc.approved_by_id = approved_by_id
        exc.updated_at = datetime.utcnow()
    return exc


def get_vendor_exceptions(db: Session, vendor_id: int) -> list[RiskException]:
    return db.query(RiskException).filter(
        RiskException.vendor_id == vendor_id
    ).order_by(RiskException.created_at.desc()).all()


def get_pending_exceptions(db: Session) -> list[RiskException]:
    return db.query(RiskException).filter(
        RiskException.status == EXCEPTION_STATUS_PENDING
    ).order_by(RiskException.created_at.desc()).all()


def check_expired_exceptions(db: Session):
    now = datetime.utcnow()
    expired = db.query(RiskException).filter(
        RiskException.status == EXCEPTION_STATUS_APPROVED,
        RiskException.expires_at != None,
        RiskException.expires_at < now,
    ).all()
    for exc in expired:
        exc.status = EXCEPTION_STATUS_EXPIRED
    if expired:
        db.commit()
    return len(expired)
