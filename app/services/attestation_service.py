"""Attestation workflow service — control owners periodically attest to control effectiveness."""

from datetime import datetime
from sqlalchemy.orm import Session, joinedload
from models import (
    ControlAttestation, ControlImplementation, Control,
    ATTESTATION_STATUS_PENDING, ATTESTATION_STATUS_ATTESTED,
    ATTESTATION_STATUS_REJECTED, ATTESTATION_STATUS_EXPIRED,
)


def request_attestation(db: Session, impl_id: int, attestor_user_id: int, due_date=None) -> ControlAttestation:
    """Create a new attestation request for a control implementation."""
    att = ControlAttestation(
        implementation_id=impl_id,
        attestor_user_id=attestor_user_id,
        status=ATTESTATION_STATUS_PENDING,
        due_date=due_date,
    )
    db.add(att)
    db.flush()
    return att


def submit_attestation(db: Session, attestation_id: int, is_effective: bool, notes: str = "", evidence_notes: str = "") -> ControlAttestation | None:
    """Submit an attestation response — marks as ATTESTED."""
    att = db.query(ControlAttestation).filter(ControlAttestation.id == attestation_id).first()
    if not att:
        return None
    att.status = ATTESTATION_STATUS_ATTESTED
    att.is_effective = is_effective
    att.notes = notes
    att.evidence_notes = evidence_notes
    att.attested_date = datetime.utcnow()
    db.flush()
    return att


def reject_attestation(db: Session, attestation_id: int, notes: str = "") -> ControlAttestation | None:
    """Owner cannot attest — marks as REJECTED with explanation."""
    att = db.query(ControlAttestation).filter(ControlAttestation.id == attestation_id).first()
    if not att:
        return None
    att.status = ATTESTATION_STATUS_REJECTED
    att.notes = notes
    att.attested_date = datetime.utcnow()
    db.flush()
    return att


def get_attestation(db: Session, attestation_id: int) -> ControlAttestation | None:
    return db.query(ControlAttestation).options(
        joinedload(ControlAttestation.implementation).joinedload(ControlImplementation.control),
        joinedload(ControlAttestation.attestor),
    ).filter(ControlAttestation.id == attestation_id).first()


def get_implementation_attestations(db: Session, impl_id: int) -> list:
    """All attestations for an implementation, newest first."""
    return db.query(ControlAttestation).options(
        joinedload(ControlAttestation.attestor),
    ).filter(
        ControlAttestation.implementation_id == impl_id
    ).order_by(ControlAttestation.created_at.desc()).all()


def get_pending_attestations(db: Session, user_id: int = None) -> list:
    """All pending attestation requests, optionally filtered by attestor."""
    q = db.query(ControlAttestation).options(
        joinedload(ControlAttestation.implementation).joinedload(ControlImplementation.control),
        joinedload(ControlAttestation.attestor),
    ).filter(ControlAttestation.status == ATTESTATION_STATUS_PENDING)
    if user_id:
        q = q.filter(ControlAttestation.attestor_user_id == user_id)
    return q.order_by(ControlAttestation.due_date.asc().nullslast()).all()


def get_latest_attestation(db: Session, impl_id: int) -> ControlAttestation | None:
    """Most recent attestation for an implementation."""
    return db.query(ControlAttestation).options(
        joinedload(ControlAttestation.attestor),
    ).filter(
        ControlAttestation.implementation_id == impl_id
    ).order_by(ControlAttestation.created_at.desc()).first()


def expire_overdue_attestations(db: Session) -> int:
    """Mark overdue PENDING attestations as EXPIRED. Returns count of expired."""
    now = datetime.utcnow()
    overdue = db.query(ControlAttestation).filter(
        ControlAttestation.status == ATTESTATION_STATUS_PENDING,
        ControlAttestation.due_date != None,
        ControlAttestation.due_date < now,
    ).all()
    for att in overdue:
        att.status = ATTESTATION_STATUS_EXPIRED
    db.flush()
    return len(overdue)
