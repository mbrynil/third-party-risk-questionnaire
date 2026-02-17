"""Remediation tracking service.

Auto-generates remediation items from risk statements on finalize,
and provides vendor-level queries and stats.
"""

from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from models import (
    RemediationItem, RiskStatement,
    REMEDIATION_SOURCE_AUTO, REMEDIATION_STATUS_OPEN, REMEDIATION_STATUS_CLOSED,
    REMEDIATION_STATUS_VERIFIED,
)


# Default due date offsets by severity
SEVERITY_DUE_DAYS = {
    "CRITICAL": 30,
    "HIGH": 60,
    "MEDIUM": 90,
    "LOW": 120,
}


def auto_generate_remediations(db: Session, decision, risk_suggestions: list) -> int:
    """Create remediation items from matched risk statements on finalize.

    Returns the count of items created.
    """
    created = 0
    now = datetime.utcnow()

    for rs in risk_suggestions:
        risk_statement_id = rs.get("risk_statement_id")
        severity = rs.get("severity", "MEDIUM")
        category = rs.get("category", "")
        finding = rs.get("finding", "")
        remediation_text = rs.get("remediation", "")

        due_days = SEVERITY_DUE_DAYS.get(severity, 90)

        item = RemediationItem(
            vendor_id=decision.vendor_id,
            assessment_id=decision.assessment_id,
            decision_id=decision.id,
            title=f"{category}: {finding[:200]}" if finding else f"{category} remediation required",
            description=remediation_text,
            source=REMEDIATION_SOURCE_AUTO,
            risk_statement_id=risk_statement_id,
            category=category,
            severity=severity,
            status=REMEDIATION_STATUS_OPEN,
            due_date=now + timedelta(days=due_days),
        )
        db.add(item)
        created += 1

    return created


def get_vendor_remediations(db: Session, vendor_id: int) -> list:
    """Get all remediation items for a vendor, sorted by severity then status."""
    severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}

    items = db.query(RemediationItem).filter(
        RemediationItem.vendor_id == vendor_id
    ).all()

    items.sort(key=lambda x: (
        severity_order.get(x.severity, 4),
        0 if x.status == REMEDIATION_STATUS_OPEN else 1,
        x.due_date or datetime.max,
    ))

    return items


def get_remediation_stats(db: Session, vendor_id: int = None) -> dict:
    """Get remediation stats, optionally filtered by vendor.

    Returns dict with counts by status and total open.
    """
    query = db.query(RemediationItem)
    if vendor_id:
        query = query.filter(RemediationItem.vendor_id == vendor_id)

    items = query.all()
    open_count = sum(
        1 for i in items
        if i.status not in (REMEDIATION_STATUS_CLOSED, REMEDIATION_STATUS_VERIFIED)
    )

    return {
        "total": len(items),
        "open": open_count,
    }


def get_open_remediation_count(db: Session) -> int:
    """Get total open remediation items across all vendors."""
    return db.query(RemediationItem).filter(
        RemediationItem.status.notin_([REMEDIATION_STATUS_CLOSED, REMEDIATION_STATUS_VERIFIED])
    ).count()
