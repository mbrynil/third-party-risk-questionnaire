"""Control notification service — aggregates control program action items and alerts."""

from datetime import datetime, timedelta
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from models import (
    ControlImplementation, ControlTest, ControlFinding, ControlAttestation, Control,
    IMPL_STATUS_IMPLEMENTED,
    TEST_STATUS_COMPLETED, TEST_STATUS_SCHEDULED,
    FINDING_STATUS_OPEN, FINDING_STATUS_IN_PROGRESS,
    ATTESTATION_STATUS_PENDING,
    CONTROL_FREQUENCY_DAYS,
)


def get_overdue_tests(db: Session) -> list:
    """Implementations with overdue testing (next_test_date in the past)."""
    now = datetime.utcnow()
    return db.query(ControlImplementation).options(
        joinedload(ControlImplementation.control),
        joinedload(ControlImplementation.owner),
    ).filter(
        ControlImplementation.vendor_id == None,
        ControlImplementation.status == IMPL_STATUS_IMPLEMENTED,
        ControlImplementation.next_test_date != None,
        ControlImplementation.next_test_date < now,
    ).order_by(ControlImplementation.next_test_date.asc()).all()


def get_upcoming_tests(db: Session, days: int = 14) -> list:
    """Implementations with tests due within N days."""
    now = datetime.utcnow()
    threshold = now + timedelta(days=days)
    return db.query(ControlImplementation).options(
        joinedload(ControlImplementation.control),
        joinedload(ControlImplementation.owner),
    ).filter(
        ControlImplementation.vendor_id == None,
        ControlImplementation.status == IMPL_STATUS_IMPLEMENTED,
        ControlImplementation.next_test_date != None,
        ControlImplementation.next_test_date >= now,
        ControlImplementation.next_test_date <= threshold,
    ).order_by(ControlImplementation.next_test_date.asc()).all()


def get_overdue_findings(db: Session) -> list:
    """Open findings past their due date."""
    now = datetime.utcnow()
    return db.query(ControlFinding).options(
        joinedload(ControlFinding.test).joinedload(ControlTest.implementation).joinedload(ControlImplementation.control),
        joinedload(ControlFinding.owner),
    ).join(
        ControlTest, ControlFinding.control_test_id == ControlTest.id
    ).join(
        ControlImplementation, ControlTest.implementation_id == ControlImplementation.id
    ).filter(
        ControlImplementation.vendor_id == None,
        ControlFinding.status.in_([FINDING_STATUS_OPEN, FINDING_STATUS_IN_PROGRESS]),
        ControlFinding.due_date != None,
        ControlFinding.due_date < now,
    ).order_by(ControlFinding.due_date.asc()).all()


def get_pending_attestations(db: Session) -> list:
    """Pending attestation requests (optionally overdue)."""
    return db.query(ControlAttestation).options(
        joinedload(ControlAttestation.implementation).joinedload(ControlImplementation.control),
        joinedload(ControlAttestation.attestor),
    ).filter(
        ControlAttestation.status == ATTESTATION_STATUS_PENDING,
    ).order_by(ControlAttestation.due_date.asc().nullslast()).all()


def get_never_tested_implementations(db: Session) -> list:
    """Implemented controls that have never been tested."""
    # Subquery: implementation IDs that have at least one completed test
    tested_ids = db.query(ControlTest.implementation_id).filter(
        ControlTest.status == TEST_STATUS_COMPLETED,
    ).distinct().subquery()

    return db.query(ControlImplementation).options(
        joinedload(ControlImplementation.control),
        joinedload(ControlImplementation.owner),
    ).filter(
        ControlImplementation.vendor_id == None,
        ControlImplementation.status == IMPL_STATUS_IMPLEMENTED,
        ~ControlImplementation.id.in_(db.query(tested_ids)),
    ).order_by(ControlImplementation.control_id).all()


def get_control_action_items(db: Session) -> list:
    """Consolidated list of all control program action items, sorted by priority.
    Returns list of dicts: [{type, priority, title, description, entity_type, entity_id, due_date, url}]
    Priority: 1=critical, 2=high, 3=medium, 4=low
    """
    items = []
    now = datetime.utcnow()

    # Overdue tests (priority 1)
    for impl in get_overdue_tests(db):
        days_overdue = (now - impl.next_test_date).days if impl.next_test_date else 0
        items.append({
            "type": "OVERDUE_TEST",
            "priority": 1,
            "title": f"Overdue test: {impl.control.control_ref}",
            "description": f"{impl.control.title} — {days_overdue} days overdue",
            "entity_type": "implementation",
            "entity_id": impl.id,
            "due_date": impl.next_test_date,
            "url": f"/controls/implementations/{impl.id}",
            "control_ref": impl.control.control_ref,
            "owner": impl.owner.display_name if impl.owner else None,
        })

    # Overdue findings (priority 1)
    for finding in get_overdue_findings(db):
        days_overdue = (now - finding.due_date).days if finding.due_date else 0
        ctrl = finding.test.implementation.control if finding.test and finding.test.implementation else None
        items.append({
            "type": "OVERDUE_FINDING",
            "priority": 1,
            "title": f"Overdue finding: {ctrl.control_ref if ctrl else 'Unknown'}",
            "description": f"{finding.severity} {finding.finding_type} — {days_overdue} days overdue",
            "entity_type": "finding",
            "entity_id": finding.id,
            "due_date": finding.due_date,
            "url": f"/controls/tests/{finding.control_test_id}#findings",
            "control_ref": ctrl.control_ref if ctrl else "?",
            "owner": finding.owner.display_name if finding.owner else None,
        })

    # Pending attestations (priority 2)
    for att in get_pending_attestations(db):
        is_overdue = att.due_date and att.due_date < now
        ctrl = att.implementation.control if att.implementation else None
        items.append({
            "type": "PENDING_ATTESTATION",
            "priority": 1 if is_overdue else 2,
            "title": f"{'Overdue' if is_overdue else 'Pending'} attestation: {ctrl.control_ref if ctrl else 'Unknown'}",
            "description": f"Requested from {att.attestor.display_name if att.attestor else 'unknown'}",
            "entity_type": "attestation",
            "entity_id": att.id,
            "due_date": att.due_date,
            "url": f"/controls/implementations/{att.implementation_id}",
            "control_ref": ctrl.control_ref if ctrl else "?",
            "owner": att.attestor.display_name if att.attestor else None,
        })

    # Upcoming tests (priority 3)
    for impl in get_upcoming_tests(db):
        days_until = (impl.next_test_date - now).days if impl.next_test_date else 0
        items.append({
            "type": "UPCOMING_TEST",
            "priority": 3,
            "title": f"Test due soon: {impl.control.control_ref}",
            "description": f"{impl.control.title} — due in {days_until} days",
            "entity_type": "implementation",
            "entity_id": impl.id,
            "due_date": impl.next_test_date,
            "url": f"/controls/implementations/{impl.id}",
            "control_ref": impl.control.control_ref,
            "owner": impl.owner.display_name if impl.owner else None,
        })

    # Never tested (priority 3)
    for impl in get_never_tested_implementations(db):
        items.append({
            "type": "NEVER_TESTED",
            "priority": 3,
            "title": f"Never tested: {impl.control.control_ref}",
            "description": f"{impl.control.title} — implemented but no tests recorded",
            "entity_type": "implementation",
            "entity_id": impl.id,
            "due_date": None,
            "url": f"/controls/implementations/{impl.id}",
            "control_ref": impl.control.control_ref,
            "owner": impl.owner.display_name if impl.owner else None,
        })

    # Sort by priority, then due_date
    items.sort(key=lambda x: (x["priority"], x["due_date"] or datetime(2099, 1, 1)))
    return items
