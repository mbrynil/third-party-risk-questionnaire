"""Compliance Calendar service — aggregates all date-based events across GRC modules."""

import calendar
from datetime import datetime, date, timedelta
from sqlalchemy.orm import Session, joinedload

from models import (
    ControlTest, ControlImplementation, Control,
    Policy, RemediationItem, Vendor, VendorDocument,
    AuditProject, AuditRequest, Risk,
    TEST_STATUS_COMPLETED,
    POLICY_STATUS_APPROVED, POLICY_STATUS_UNDER_REVIEW,
)


# Category colors for calendar rendering
CATEGORY_COLORS = {
    "test": "#0d6efd",       # blue
    "policy": "#6f42c1",     # purple
    "remediation": "#fd7e14", # orange
    "audit": "#198754",      # green
    "contract": "#6c757d",   # gray
    "document": "#495057",   # dark gray
    "risk": "#dc3545",       # red
}


def get_calendar_events(db: Session, year: int, month: int) -> list:
    """Return all compliance events for a given month + the next 30 days for the upcoming list."""
    now = datetime.utcnow()
    today = now.date()

    # Expand window: first of month to last of month + 30 days for upcoming
    first_of_month = date(year, month, 1)
    _, last_day = calendar.monthrange(year, month)
    last_of_month = date(year, month, last_day)
    upcoming_end = today + timedelta(days=30)

    # Use the widest window
    window_start = min(first_of_month, today)
    window_end = max(last_of_month, upcoming_end)

    dt_start = datetime(window_start.year, window_start.month, window_start.day)
    dt_end = datetime(window_end.year, window_end.month, window_end.day, 23, 59, 59)

    events = []

    # ---- 1. Control Tests (scheduled_date) ----
    tests = db.query(ControlTest).options(
        joinedload(ControlTest.implementation).joinedload(ControlImplementation.control),
    ).filter(
        ControlTest.scheduled_date != None,
        ControlTest.scheduled_date >= dt_start,
        ControlTest.scheduled_date <= dt_end,
    ).all()

    for t in tests:
        ctrl = t.implementation.control if t.implementation else None
        d = t.scheduled_date.date() if t.scheduled_date else None
        if d:
            events.append({
                "date": d,
                "title": f"Control Test: {ctrl.control_ref} - {t.test_type}" if ctrl else f"Control Test #{t.id}",
                "link": f"/controls/tests/{t.id}",
                "category": "test",
                "color": CATEGORY_COLORS["test"],
                "is_overdue": d < today and t.status != TEST_STATUS_COMPLETED,
            })

    # ---- 2. Policy Reviews (next_review_date) ----
    policies = db.query(Policy).filter(
        Policy.is_active == True,
        Policy.next_review_date != None,
        Policy.next_review_date >= dt_start,
        Policy.next_review_date <= dt_end,
    ).all()

    for p in policies:
        d = p.next_review_date.date() if p.next_review_date else None
        if d:
            events.append({
                "date": d,
                "title": f"Policy Review: {p.policy_ref} - {p.title}",
                "link": f"/policies/{p.id}",
                "category": "policy",
                "color": CATEGORY_COLORS["policy"],
                "is_overdue": d < today and p.status in (POLICY_STATUS_APPROVED,),
            })

    # ---- 3. Remediation Due Dates ----
    rems = db.query(RemediationItem).options(
        joinedload(RemediationItem.vendor),
    ).filter(
        RemediationItem.due_date != None,
        RemediationItem.due_date >= dt_start,
        RemediationItem.due_date <= dt_end,
    ).all()

    for r in rems:
        d = r.due_date.date() if r.due_date else None
        if d:
            events.append({
                "date": d,
                "title": f"Remediation Due: {r.title}",
                "link": f"/vendors/{r.vendor_id}/remediations/{r.id}" if r.vendor_id else "#",
                "category": "remediation",
                "color": CATEGORY_COLORS["remediation"],
                "is_overdue": d < today and r.status not in ("VERIFIED", "CLOSED"),
            })

    # ---- 4. Audit Project Deadlines ----
    audit_projects = db.query(AuditProject).filter(
        AuditProject.due_date != None,
        AuditProject.due_date >= dt_start,
        AuditProject.due_date <= dt_end,
    ).all()

    for ap in audit_projects:
        d = ap.due_date.date() if ap.due_date else None
        if d:
            events.append({
                "date": d,
                "title": f"Audit Due: {ap.title}",
                "link": f"/audits/{ap.id}",
                "category": "audit",
                "color": CATEGORY_COLORS["audit"],
                "is_overdue": d < today and ap.status not in ("COMPLETED", "CANCELLED"),
            })

    # ---- 5. Audit Request Deadlines ----
    audit_reqs = db.query(AuditRequest).options(
        joinedload(AuditRequest.audit_project),
    ).filter(
        AuditRequest.due_date != None,
        AuditRequest.due_date >= dt_start,
        AuditRequest.due_date <= dt_end,
    ).all()

    for ar in audit_reqs:
        d = ar.due_date.date() if ar.due_date else None
        if d:
            events.append({
                "date": d,
                "title": f"Audit Request: {ar.request_title}",
                "link": f"/audits/{ar.audit_project_id}/requests/{ar.id}" if ar.audit_project_id else "#",
                "category": "audit",
                "color": CATEGORY_COLORS["audit"],
                "is_overdue": d < today and ar.status in ("OPEN", "IN_PROGRESS"),
            })

    # ---- 6. Vendor Contract Expiry ----
    vendors = db.query(Vendor).filter(
        Vendor.contract_end_date != None,
        Vendor.contract_end_date >= dt_start,
        Vendor.contract_end_date <= dt_end,
    ).all()

    for v in vendors:
        d = v.contract_end_date.date() if v.contract_end_date else None
        if d:
            events.append({
                "date": d,
                "title": f"Contract Expiry: {v.name}",
                "link": f"/vendors/{v.id}",
                "category": "contract",
                "color": CATEGORY_COLORS["contract"],
                "is_overdue": d < today,
            })

    # ---- 7. Vendor Document Expiry ----
    docs = db.query(VendorDocument).options(
        joinedload(VendorDocument.vendor),
    ).filter(
        VendorDocument.expiry_date != None,
        VendorDocument.expiry_date >= dt_start,
        VendorDocument.expiry_date <= dt_end,
    ).all()

    for doc in docs:
        d = doc.expiry_date.date() if doc.expiry_date else None
        if d:
            v_name = doc.vendor.name if doc.vendor else "Unknown"
            events.append({
                "date": d,
                "title": f"Doc Expiry: {v_name} - {doc.document_type}",
                "link": f"/vendors/{doc.vendor_id}" if doc.vendor_id else "#",
                "category": "document",
                "color": CATEGORY_COLORS["document"],
                "is_overdue": d < today,
            })

    # ---- 8. Risk Reviews (next_review_date) ----
    risks = db.query(Risk).filter(
        Risk.is_active == True,
        Risk.next_review_date != None,
        Risk.next_review_date >= dt_start,
        Risk.next_review_date <= dt_end,
    ).all()

    for risk in risks:
        d = risk.next_review_date.date() if risk.next_review_date else None
        if d:
            events.append({
                "date": d,
                "title": f"Risk Review: {risk.risk_ref}",
                "link": f"/risks/{risk.id}",
                "category": "risk",
                "color": CATEGORY_COLORS["risk"],
                "is_overdue": d < today,
            })

    # Sort by date
    events.sort(key=lambda e: e["date"])
    return events


def build_calendar_grid(year: int, month: int) -> dict:
    """Build a month grid for HTML rendering."""
    cal = calendar.Calendar(firstweekday=0)  # Monday start
    month_days = cal.monthdayscalendar(year, month)
    month_name = calendar.month_name[month]
    today = date.today()

    # Previous / next month
    if month == 1:
        prev_year, prev_month = year - 1, 12
    else:
        prev_year, prev_month = year, month - 1

    if month == 12:
        next_year, next_month = year + 1, 1
    else:
        next_year, next_month = year, month + 1

    return {
        "year": year,
        "month": month,
        "month_name": month_name,
        "weeks": month_days,
        "today": today,
        "prev_year": prev_year,
        "prev_month": prev_month,
        "next_year": next_year,
        "next_month": next_month,
        "day_headers": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    }
