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


def get_overdue_remediation_count(db: Session) -> int:
    """Get total overdue remediation items (past due date and not closed/verified)."""
    now = datetime.utcnow()
    return db.query(RemediationItem).filter(
        RemediationItem.due_date < now,
        RemediationItem.status.notin_([REMEDIATION_STATUS_CLOSED, REMEDIATION_STATUS_VERIFIED])
    ).count()


def get_portfolio_remediation_summary(db: Session) -> dict:
    """Get portfolio-wide remediation summary for the print report."""
    now = datetime.utcnow()
    items = db.query(RemediationItem).all()

    total = len(items)
    open_count = sum(
        1 for i in items
        if i.status not in (REMEDIATION_STATUS_CLOSED, REMEDIATION_STATUS_VERIFIED)
    )
    closed_count = sum(
        1 for i in items
        if i.status in (REMEDIATION_STATUS_CLOSED, REMEDIATION_STATUS_VERIFIED)
    )
    overdue_count = sum(
        1 for i in items
        if i.due_date and i.due_date < now
        and i.status not in (REMEDIATION_STATUS_CLOSED, REMEDIATION_STATUS_VERIFIED)
    )

    severity_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for i in items:
        if i.severity in severity_counts:
            severity_counts[i.severity] += 1

    # Top 10 most overdue items
    overdue_items = [
        i for i in items
        if i.due_date and i.due_date < now
        and i.status not in (REMEDIATION_STATUS_CLOSED, REMEDIATION_STATUS_VERIFIED)
    ]
    overdue_items.sort(key=lambda x: x.due_date)
    overdue_items = overdue_items[:10]

    overdue_list = []
    for i in overdue_items:
        days_overdue = (now - i.due_date).days
        overdue_list.append({
            "id": i.id,
            "title": i.title,
            "severity": i.severity,
            "due_date": i.due_date.strftime("%Y-%m-%d"),
            "days_overdue": days_overdue,
            "vendor": i.vendor,
        })

    return {
        "total": total,
        "open": open_count,
        "closed": closed_count,
        "overdue": overdue_count,
        "severity_counts": severity_counts,
        "overdue_items": overdue_list,
    }
