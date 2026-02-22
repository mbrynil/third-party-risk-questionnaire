"""Unified Task Center service — aggregates actionable tasks across all GRC modules."""

from datetime import datetime, timedelta
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_

from models import (
    ControlTest, ControlImplementation, Control,
    ControlAttestation, ControlFinding,
    RemediationItem, Vendor,
    Policy, PolicyAcknowledgment,
    AuditRequest, AuditProject,
    Risk, User,
    TEST_STATUS_COMPLETED, TEST_STATUS_SCHEDULED, TEST_STATUS_IN_PROGRESS,
    ATTESTATION_STATUS_PENDING,
    FINDING_STATUS_OPEN, FINDING_STATUS_IN_PROGRESS,
    REMEDIATION_STATUS_VERIFIED, REMEDIATION_STATUS_CLOSED,
    POLICY_STATUS_APPROVED,
)


def get_my_tasks(db: Session, user_id: int) -> dict:
    """Return categorised task lists for the given user."""
    now = datetime.utcnow()
    today = now.date()
    threshold_30 = now + timedelta(days=30)
    week_end = now + timedelta(days=7)
    day_start = datetime(now.year, now.month, now.day)
    day_end = day_start + timedelta(days=1)

    tasks = {}

    # ---- 1. Tests Due (assigned as tester, not completed, due in 30 days or in-progress) ----
    tests_due_q = db.query(ControlTest).options(
        joinedload(ControlTest.implementation).joinedload(ControlImplementation.control),
    ).filter(
        ControlTest.tester_user_id == user_id,
        ControlTest.status != TEST_STATUS_COMPLETED,
        or_(
            and_(ControlTest.scheduled_date != None, ControlTest.scheduled_date <= threshold_30),
            ControlTest.status == TEST_STATUS_IN_PROGRESS,
        ),
    ).order_by(ControlTest.scheduled_date.asc().nullsfirst()).all()

    tasks["tests_due"] = []
    for t in tests_due_q:
        ctrl = t.implementation.control if t.implementation else None
        due = t.scheduled_date
        is_overdue = due is not None and due < now
        tasks["tests_due"].append({
            "id": t.id,
            "type": "Control Test",
            "icon": "bi-clipboard-check",
            "title": f"{ctrl.control_ref} - {t.test_type} test" if ctrl else f"Test #{t.id}",
            "description": ctrl.title if ctrl else "",
            "due_date": due,
            "is_overdue": is_overdue,
            "status": t.status,
            "link": f"/controls/tests/{t.id}",
            "priority": "HIGH" if is_overdue else ("MEDIUM" if t.status == TEST_STATUS_IN_PROGRESS else "LOW"),
        })

    # ---- 2. Tests to Review (assigned as reviewer, completed but not yet reviewed) ----
    tests_review_q = db.query(ControlTest).options(
        joinedload(ControlTest.implementation).joinedload(ControlImplementation.control),
    ).filter(
        ControlTest.reviewer_user_id == user_id,
        ControlTest.status == TEST_STATUS_COMPLETED,
        ControlTest.review_date == None,
    ).order_by(ControlTest.test_date.desc()).all()

    tasks["tests_to_review"] = []
    for t in tests_review_q:
        ctrl = t.implementation.control if t.implementation else None
        tasks["tests_to_review"].append({
            "id": t.id,
            "type": "Test Review",
            "icon": "bi-pencil-square",
            "title": f"Review: {ctrl.control_ref} - {t.test_type}" if ctrl else f"Review Test #{t.id}",
            "description": ctrl.title if ctrl else "",
            "due_date": None,
            "is_overdue": False,
            "status": "NEEDS_REVIEW",
            "link": f"/controls/tests/{t.id}",
            "priority": "MEDIUM",
        })

    # ---- 3. Remediations ----
    rems = db.query(RemediationItem).options(
        joinedload(RemediationItem.vendor),
    ).filter(
        RemediationItem.assigned_to_user_id == user_id,
        ~RemediationItem.status.in_([REMEDIATION_STATUS_VERIFIED, REMEDIATION_STATUS_CLOSED]),
    ).order_by(RemediationItem.due_date.asc().nullsfirst()).all()

    tasks["remediations"] = []
    for r in rems:
        is_overdue = r.due_date is not None and r.due_date < now
        tasks["remediations"].append({
            "id": r.id,
            "type": "Remediation",
            "icon": "bi-wrench-adjustable",
            "title": r.title,
            "description": r.vendor.name if r.vendor else "",
            "due_date": r.due_date,
            "is_overdue": is_overdue,
            "status": r.status,
            "link": f"/vendors/{r.vendor_id}/remediations/{r.id}" if r.vendor_id else "#",
            "priority": "HIGH" if is_overdue else ("MEDIUM" if r.severity in ("HIGH", "CRITICAL") else "LOW"),
        })

    # ---- 4. Policy Reviews ----
    policy_reviews = db.query(Policy).filter(
        Policy.owner_user_id == user_id,
        Policy.status == POLICY_STATUS_APPROVED,
        Policy.is_active == True,
        Policy.next_review_date != None,
        Policy.next_review_date <= threshold_30,
    ).order_by(Policy.next_review_date.asc()).all()

    tasks["policy_reviews"] = []
    for p in policy_reviews:
        is_overdue = p.next_review_date is not None and p.next_review_date < now
        tasks["policy_reviews"].append({
            "id": p.id,
            "type": "Policy Review",
            "icon": "bi-file-earmark-text",
            "title": f"{p.policy_ref} - {p.title}",
            "description": "Review due",
            "due_date": p.next_review_date,
            "is_overdue": is_overdue,
            "status": "REVIEW_DUE",
            "link": f"/policies/{p.id}",
            "priority": "HIGH" if is_overdue else "MEDIUM",
        })

    # ---- 5. Policy Acknowledgments ----
    # Approved active policies the user has NOT acknowledged (or acknowledged an older version)
    approved_policies = db.query(Policy).filter(
        Policy.status == POLICY_STATUS_APPROVED,
        Policy.is_active == True,
    ).all()

    acked_policy_ids = set()
    if approved_policies:
        acks = db.query(PolicyAcknowledgment).filter(
            PolicyAcknowledgment.user_id == user_id,
            PolicyAcknowledgment.policy_id.in_([p.id for p in approved_policies]),
        ).all()
        for ack in acks:
            # Consider acknowledged if version matches current
            policy_map = {p.id: p for p in approved_policies}
            pol = policy_map.get(ack.policy_id)
            if pol and (ack.version_acknowledged is None or ack.version_acknowledged >= pol.version):
                acked_policy_ids.add(ack.policy_id)

    tasks["policy_acks"] = []
    for p in approved_policies:
        if p.id not in acked_policy_ids:
            tasks["policy_acks"].append({
                "id": p.id,
                "type": "Policy Acknowledgment",
                "icon": "bi-check2-square",
                "title": f"Acknowledge: {p.policy_ref} - {p.title}",
                "description": f"Version {p.version}",
                "due_date": None,
                "is_overdue": False,
                "status": "PENDING",
                "link": f"/policies/{p.id}",
                "priority": "LOW",
            })

    # ---- 6. Attestations ----
    attestations = db.query(ControlAttestation).options(
        joinedload(ControlAttestation.implementation).joinedload(ControlImplementation.control),
    ).filter(
        ControlAttestation.attestor_user_id == user_id,
        ControlAttestation.status == ATTESTATION_STATUS_PENDING,
    ).order_by(ControlAttestation.due_date.asc().nullsfirst()).all()

    tasks["attestations"] = []
    for a in attestations:
        ctrl = a.implementation.control if a.implementation else None
        is_overdue = a.due_date is not None and a.due_date < now
        tasks["attestations"].append({
            "id": a.id,
            "type": "Attestation",
            "icon": "bi-patch-check",
            "title": f"Attest: {ctrl.control_ref} - {ctrl.title}" if ctrl else f"Attestation #{a.id}",
            "description": "",
            "due_date": a.due_date,
            "is_overdue": is_overdue,
            "status": "PENDING",
            "link": f"/controls/attestations/{a.id}",
            "priority": "HIGH" if is_overdue else "MEDIUM",
        })

    # ---- 7. Audit Requests ----
    audit_reqs = db.query(AuditRequest).options(
        joinedload(AuditRequest.audit_project),
    ).filter(
        AuditRequest.assigned_to_user_id == user_id,
        AuditRequest.status.in_(["OPEN", "IN_PROGRESS"]),
    ).order_by(AuditRequest.due_date.asc().nullsfirst()).all()

    tasks["audit_requests"] = []
    for ar in audit_reqs:
        is_overdue = ar.due_date is not None and ar.due_date < now
        tasks["audit_requests"].append({
            "id": ar.id,
            "type": "Audit Request",
            "icon": "bi-clipboard-check",
            "title": ar.request_title,
            "description": ar.audit_project.title if ar.audit_project else "",
            "due_date": ar.due_date,
            "is_overdue": is_overdue,
            "status": ar.status,
            "link": f"/audits/{ar.audit_project_id}/requests/{ar.id}" if ar.audit_project_id else "#",
            "priority": "HIGH" if is_overdue or ar.priority == "HIGH" else ("MEDIUM" if ar.priority == "MEDIUM" else "LOW"),
        })

    # ---- 8. Findings ----
    findings = db.query(ControlFinding).options(
        joinedload(ControlFinding.test).joinedload(ControlTest.implementation).joinedload(ControlImplementation.control),
    ).filter(
        ControlFinding.owner_user_id == user_id,
        ControlFinding.status.in_([FINDING_STATUS_OPEN, FINDING_STATUS_IN_PROGRESS]),
    ).order_by(ControlFinding.due_date.asc().nullsfirst()).all()

    tasks["findings"] = []
    for f in findings:
        ctrl = None
        if f.test and f.test.implementation:
            ctrl = f.test.implementation.control
        is_overdue = f.due_date is not None and f.due_date < now
        tasks["findings"].append({
            "id": f.id,
            "type": "Finding",
            "icon": "bi-exclamation-triangle",
            "title": f"Finding: {ctrl.control_ref}" if ctrl else f"Finding #{f.id}",
            "description": f.condition or f.criteria or "",
            "due_date": f.due_date,
            "is_overdue": is_overdue,
            "status": f.status,
            "link": f"/controls/findings/{f.id}",
            "priority": "HIGH" if f.severity in ("HIGH", "CRITICAL") or is_overdue else "MEDIUM",
        })

    # ---- Compute summary counts ----
    all_items = []
    for key in ["tests_due", "tests_to_review", "remediations", "policy_reviews",
                 "policy_acks", "attestations", "audit_requests", "findings"]:
        all_items.extend(tasks[key])

    tasks["total_count"] = len(all_items)
    tasks["overdue_count"] = sum(1 for t in all_items if t.get("is_overdue"))
    tasks["due_this_week"] = sum(
        1 for t in all_items
        if t.get("due_date") and not t.get("is_overdue") and t["due_date"] <= week_end
    )

    # Section labels and keys for template rendering
    tasks["sections"] = [
        ("tests_due", "Tests Due", "bi-clipboard-check", "#0d6efd"),
        ("tests_to_review", "Tests to Review", "bi-pencil-square", "#6610f2"),
        ("remediations", "Remediations", "bi-wrench-adjustable", "#fd7e14"),
        ("policy_reviews", "Policy Reviews", "bi-file-earmark-text", "#6f42c1"),
        ("policy_acks", "Policy Acknowledgments", "bi-check2-square", "#20c997"),
        ("attestations", "Attestations", "bi-patch-check", "#d63384"),
        ("audit_requests", "Audit Requests", "bi-clipboard-check", "#198754"),
        ("findings", "Findings", "bi-exclamation-triangle", "#dc3545"),
    ]

    return tasks
