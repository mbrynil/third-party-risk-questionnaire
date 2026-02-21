"""Control library service — CRUD for controls, implementations, testing, and evidence."""

import os
import uuid
from datetime import datetime, timedelta
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from models import (
    Control, ControlFrameworkMapping, ControlQuestionMapping, ControlRiskMapping,
    ControlImplementation, ControlTest, ControlEvidence, ControlFinding,
    IMPL_STATUS_NOT_IMPLEMENTED, IMPL_STATUS_IMPLEMENTED,
    CONTROL_FREQUENCY_DAYS,
    TEST_STATUS_SCHEDULED, TEST_STATUS_IN_PROGRESS, TEST_STATUS_COMPLETED,
    TEST_RESULT_NOT_TESTED,
    FINDING_STATUS_OPEN, FINDING_STATUS_CLOSED,
)


# ==================== CONTROL LIBRARY ====================

def get_all_controls(db: Session, active_only: bool = True):
    q = db.query(Control).options(
        joinedload(Control.framework_mappings),
    )
    if active_only:
        q = q.filter(Control.is_active == True)
    return q.order_by(Control.domain, Control.control_ref).all()


def get_control(db: Session, control_id: int):
    return db.query(Control).options(
        joinedload(Control.framework_mappings),
        joinedload(Control.question_mappings).joinedload(ControlQuestionMapping.question_bank_item),
        joinedload(Control.risk_mappings).joinedload(ControlRiskMapping.risk_statement),
        joinedload(Control.owner),
    ).filter(Control.id == control_id).first()


def get_controls_by_domain(db: Session, active_only: bool = True) -> dict:
    controls = get_all_controls(db, active_only)
    grouped = {}
    for c in controls:
        grouped.setdefault(c.domain, []).append(c)
    return grouped


def create_control(db: Session, **kwargs) -> Control:
    ctrl = Control(**kwargs)
    db.add(ctrl)
    db.flush()
    return ctrl


def update_control(db: Session, control_id: int, **kwargs) -> Control | None:
    ctrl = db.query(Control).filter(Control.id == control_id).first()
    if not ctrl:
        return None
    for k, v in kwargs.items():
        if hasattr(ctrl, k):
            setattr(ctrl, k, v)
    return ctrl


def delete_control(db: Session, control_id: int) -> bool:
    ctrl = db.query(Control).filter(Control.id == control_id).first()
    if not ctrl:
        return False
    db.delete(ctrl)
    return True


def set_framework_mappings(db: Session, control_id: int, mappings: list[tuple[str, str]]):
    db.query(ControlFrameworkMapping).filter(
        ControlFrameworkMapping.control_id == control_id
    ).delete()
    for framework, reference in mappings:
        if framework.strip() and reference.strip():
            db.add(ControlFrameworkMapping(
                control_id=control_id, framework=framework.strip(), reference=reference.strip(),
            ))


def set_question_mappings(db: Session, control_id: int, ids: list[int]):
    db.query(ControlQuestionMapping).filter(
        ControlQuestionMapping.control_id == control_id
    ).delete()
    for qid in ids:
        db.add(ControlQuestionMapping(control_id=control_id, question_bank_item_id=qid))


def set_risk_mappings(db: Session, control_id: int, ids: list[int]):
    db.query(ControlRiskMapping).filter(
        ControlRiskMapping.control_id == control_id
    ).delete()
    for rid in ids:
        db.add(ControlRiskMapping(control_id=control_id, risk_statement_id=rid))


def get_last_tested_date(db: Session, control_id: int):
    """Most recent test date across all implementations of a control."""
    result = db.query(func.max(ControlTest.test_date)).join(
        ControlImplementation, ControlTest.implementation_id == ControlImplementation.id
    ).filter(ControlImplementation.control_id == control_id).scalar()
    return result


def get_last_tested_dates(db: Session, control_ids: list[int]) -> dict:
    """Batch lookup: {control_id: last_test_date} for multiple controls."""
    if not control_ids:
        return {}
    rows = db.query(
        ControlImplementation.control_id,
        func.max(ControlTest.test_date),
    ).join(
        ControlTest, ControlTest.implementation_id == ControlImplementation.id
    ).filter(
        ControlImplementation.control_id.in_(control_ids)
    ).group_by(ControlImplementation.control_id).all()
    return {cid: dt for cid, dt in rows}


def get_controls_by_framework(db: Session, framework_key: str):
    mappings = db.query(ControlFrameworkMapping).filter(
        ControlFrameworkMapping.framework == framework_key
    ).all()
    control_ids = [m.control_id for m in mappings]
    if not control_ids:
        return []
    controls = db.query(Control).options(
        joinedload(Control.framework_mappings),
    ).filter(Control.id.in_(control_ids), Control.is_active == True).order_by(Control.control_ref).all()
    ref_map = {m.control_id: m.reference for m in mappings}
    return [(c, ref_map.get(c.id, "")) for c in controls]


def get_control_library_stats(db: Session) -> dict:
    total = db.query(Control).count()
    active = db.query(Control).filter(Control.is_active == True).count()
    frameworks = db.query(ControlFrameworkMapping.framework).distinct().count()
    domains = db.query(Control.domain).filter(Control.is_active == True).distinct().count()
    return {"total": total, "active": active, "frameworks_covered": frameworks, "domains": domains}


# ==================== CONTROL IMPLEMENTATIONS ====================

def get_vendor_implementations(db: Session, vendor_id: int):
    return db.query(ControlImplementation).options(
        joinedload(ControlImplementation.control).joinedload(Control.framework_mappings),
        joinedload(ControlImplementation.owner),
    ).filter(
        ControlImplementation.vendor_id == vendor_id
    ).order_by(ControlImplementation.control_id).all()


def get_org_implementations(db: Session):
    return db.query(ControlImplementation).options(
        joinedload(ControlImplementation.control).joinedload(Control.framework_mappings),
        joinedload(ControlImplementation.owner),
    ).filter(
        ControlImplementation.vendor_id == None
    ).order_by(ControlImplementation.control_id).all()


def get_implementation(db: Session, impl_id: int):
    return db.query(ControlImplementation).options(
        joinedload(ControlImplementation.control).joinedload(Control.framework_mappings),
        joinedload(ControlImplementation.vendor),
        joinedload(ControlImplementation.owner),
        joinedload(ControlImplementation.tests).joinedload(ControlTest.tester),
    ).filter(ControlImplementation.id == impl_id).first()


def create_implementation(db: Session, control_id: int, vendor_id: int = None, **kwargs) -> ControlImplementation:
    impl = ControlImplementation(control_id=control_id, vendor_id=vendor_id, **kwargs)
    db.add(impl)
    db.flush()
    return impl


def update_implementation(db: Session, impl_id: int, **kwargs) -> ControlImplementation | None:
    impl = db.query(ControlImplementation).filter(ControlImplementation.id == impl_id).first()
    if not impl:
        return None
    for k, v in kwargs.items():
        if hasattr(impl, k):
            setattr(impl, k, v)
    return impl


def delete_implementation(db: Session, impl_id: int) -> bool:
    impl = db.query(ControlImplementation).filter(ControlImplementation.id == impl_id).first()
    if not impl:
        return False
    db.delete(impl)
    return True


def bulk_create_implementations(db: Session, vendor_id: int, control_ids: list[int]) -> int:
    existing = set(
        r[0] for r in db.query(ControlImplementation.control_id).filter(
            ControlImplementation.vendor_id == vendor_id,
            ControlImplementation.control_id.in_(control_ids),
        ).all()
    )
    created = 0
    for cid in control_ids:
        if cid not in existing:
            db.add(ControlImplementation(
                control_id=cid, vendor_id=vendor_id,
                status=IMPL_STATUS_NOT_IMPLEMENTED,
            ))
            created += 1
    return created


def bulk_create_org_implementations(db: Session, control_ids: list[int]) -> int:
    """Create org-level implementations (vendor_id=NULL) for controls that don't already have one."""
    existing = set(
        r[0] for r in db.query(ControlImplementation.control_id).filter(
            ControlImplementation.vendor_id == None,
            ControlImplementation.control_id.in_(control_ids),
        ).all()
    )
    created = 0
    for cid in control_ids:
        if cid not in existing:
            db.add(ControlImplementation(
                control_id=cid, vendor_id=None,
                status=IMPL_STATUS_NOT_IMPLEMENTED,
            ))
            created += 1
    return created


def get_vendor_control_stats(db: Session, vendor_id: int) -> dict:
    impls = db.query(ControlImplementation).filter(
        ControlImplementation.vendor_id == vendor_id
    ).all()
    total = len(impls)
    if total == 0:
        return {"total": 0, "implemented": 0, "partial": 0, "planned": 0, "not_implemented": 0, "na": 0, "effectiveness_pct": 0}

    counts = {}
    for impl in impls:
        counts[impl.status] = counts.get(impl.status, 0) + 1

    from models import (
        IMPL_STATUS_PLANNED, IMPL_STATUS_PARTIAL,
        IMPL_STATUS_NOT_APPLICABLE, EFFECTIVENESS_EFFECTIVE,
        EFFECTIVENESS_LARGELY_EFFECTIVE,
    )
    effective = sum(1 for i in impls if i.effectiveness in (EFFECTIVENESS_EFFECTIVE, EFFECTIVENESS_LARGELY_EFFECTIVE))
    applicable = total - counts.get(IMPL_STATUS_NOT_APPLICABLE, 0)

    return {
        "total": total,
        "implemented": counts.get(IMPL_STATUS_IMPLEMENTED, 0),
        "partial": counts.get(IMPL_STATUS_PARTIAL, 0),
        "planned": counts.get(IMPL_STATUS_PLANNED, 0),
        "not_implemented": counts.get(IMPL_STATUS_NOT_IMPLEMENTED, 0),
        "na": counts.get(IMPL_STATUS_NOT_APPLICABLE, 0),
        "effectiveness_pct": round(effective / applicable * 100) if applicable > 0 else 0,
    }


def get_org_control_stats(db: Session) -> dict:
    """Stats for org-level implementations (vendor_id IS NULL)."""
    impls = db.query(ControlImplementation).filter(
        ControlImplementation.vendor_id == None
    ).all()
    total = len(impls)
    if total == 0:
        return {"total": 0, "implemented": 0, "partial": 0, "planned": 0, "not_implemented": 0, "na": 0, "effectiveness_pct": 0}

    counts = {}
    for impl in impls:
        counts[impl.status] = counts.get(impl.status, 0) + 1

    from models import (
        IMPL_STATUS_PLANNED, IMPL_STATUS_PARTIAL,
        IMPL_STATUS_NOT_APPLICABLE, EFFECTIVENESS_EFFECTIVE,
        EFFECTIVENESS_LARGELY_EFFECTIVE,
    )
    effective = sum(1 for i in impls if i.effectiveness in (EFFECTIVENESS_EFFECTIVE, EFFECTIVENESS_LARGELY_EFFECTIVE))
    applicable = total - counts.get(IMPL_STATUS_NOT_APPLICABLE, 0)

    return {
        "total": total,
        "implemented": counts.get(IMPL_STATUS_IMPLEMENTED, 0),
        "partial": counts.get(IMPL_STATUS_PARTIAL, 0),
        "planned": counts.get(IMPL_STATUS_PLANNED, 0),
        "not_implemented": counts.get(IMPL_STATUS_NOT_IMPLEMENTED, 0),
        "na": counts.get(IMPL_STATUS_NOT_APPLICABLE, 0),
        "effectiveness_pct": round(effective / applicable * 100) if applicable > 0 else 0,
    }


# ==================== CONTROL TESTING ====================

def create_test(db: Session, impl_id: int, test_type: str,
                tester_id: int | None) -> ControlTest:
    """Create a new ad-hoc test in IN_PROGRESS status — the analyst's workspace."""
    test = ControlTest(
        implementation_id=impl_id,
        test_type=test_type,
        tester_user_id=tester_id,
        status=TEST_STATUS_IN_PROGRESS,
        result=TEST_RESULT_NOT_TESTED,
    )
    db.add(test)
    db.flush()
    # No test_date yet — set when finalized
    test.test_date = None
    return test


def get_implementation_tests(db: Session, impl_id: int):
    return db.query(ControlTest).options(
        joinedload(ControlTest.tester),
        joinedload(ControlTest.evidence_files),
    ).filter(
        ControlTest.implementation_id == impl_id
    ).order_by(ControlTest.test_date.desc()).all()


def get_test(db: Session, test_id: int):
    return db.query(ControlTest).options(
        joinedload(ControlTest.tester),
        joinedload(ControlTest.reviewer),
        joinedload(ControlTest.evidence_files),
        joinedload(ControlTest.implementation).joinedload(ControlImplementation.control).joinedload(Control.owner),
        joinedload(ControlTest.implementation).joinedload(ControlImplementation.vendor),
    ).filter(ControlTest.id == test_id).first()


def get_overdue_tests(db: Session):
    now = datetime.utcnow()
    return db.query(ControlImplementation).options(
        joinedload(ControlImplementation.control),
        joinedload(ControlImplementation.owner),
    ).filter(
        ControlImplementation.next_test_date < now,
        ControlImplementation.status == IMPL_STATUS_IMPLEMENTED,
        ControlImplementation.vendor_id == None,
    ).all()


def get_upcoming_tests(db: Session, days: int = 30):
    now = datetime.utcnow()
    threshold = now + timedelta(days=days)
    return db.query(ControlImplementation).options(
        joinedload(ControlImplementation.control),
        joinedload(ControlImplementation.owner),
    ).filter(
        ControlImplementation.next_test_date >= now,
        ControlImplementation.next_test_date <= threshold,
        ControlImplementation.status == IMPL_STATUS_IMPLEMENTED,
        ControlImplementation.vendor_id == None,
    ).all()


def update_next_test_date(db: Session, implementation):
    if not implementation or not implementation.control:
        return
    freq_days = CONTROL_FREQUENCY_DAYS.get(implementation.control.test_frequency, 365)
    latest_test = db.query(ControlTest).filter(
        ControlTest.implementation_id == implementation.id
    ).order_by(ControlTest.test_date.desc()).first()
    base_date = latest_test.test_date if latest_test else datetime.utcnow()
    implementation.next_test_date = base_date + timedelta(days=freq_days)


def get_all_testing_schedule(db: Session):
    """All IMPLEMENTED org-level control implementations — the internal testing obligation backlog."""
    return db.query(ControlImplementation).options(
        joinedload(ControlImplementation.control),
        joinedload(ControlImplementation.owner),
    ).filter(
        ControlImplementation.status == IMPL_STATUS_IMPLEMENTED,
        ControlImplementation.vendor_id == None,
    ).order_by(
        ControlImplementation.next_test_date.asc().nullsfirst(),
    ).all()


def get_all_test_history(db: Session, limit: int = 200):
    """Most recent completed test executions across org-level implementations."""
    return db.query(ControlTest).options(
        joinedload(ControlTest.tester),
        joinedload(ControlTest.evidence_files),
        joinedload(ControlTest.implementation).joinedload(ControlImplementation.control),
        joinedload(ControlTest.implementation).joinedload(ControlImplementation.owner),
    ).join(
        ControlImplementation, ControlTest.implementation_id == ControlImplementation.id
    ).filter(
        ControlTest.status == TEST_STATUS_COMPLETED,
        ControlImplementation.vendor_id == None,
    ).order_by(ControlTest.test_date.desc()).limit(limit).all()


def create_scheduled_test(db: Session, impl_id: int, test_type: str,
                          scheduled_date: datetime, tester_id: int | None) -> ControlTest:
    """Create a scheduled (future) test — does NOT update next_test_date."""
    test = ControlTest(
        implementation_id=impl_id,
        test_type=test_type,
        status=TEST_STATUS_SCHEDULED,
        scheduled_date=scheduled_date,
        tester_user_id=tester_id,
        result=TEST_RESULT_NOT_TESTED,
    )
    db.add(test)
    db.flush()
    # Override column default — scheduled tests have no test_date yet
    test.test_date = None
    return test


def start_test(db: Session, test_id: int) -> ControlTest | None:
    """Transition a SCHEDULED test to IN_PROGRESS — analyst begins working it."""
    test = db.query(ControlTest).filter(ControlTest.id == test_id).first()
    if not test or test.status != TEST_STATUS_SCHEDULED:
        return None
    test.status = TEST_STATUS_IN_PROGRESS
    db.flush()
    return test


def save_test_progress(db: Session, test_id: int, **kwargs) -> ControlTest | None:
    """Save work-in-progress on an IN_PROGRESS test without finalizing."""
    test = db.query(ControlTest).filter(ControlTest.id == test_id).first()
    if not test or test.status != TEST_STATUS_IN_PROGRESS:
        return None
    for k, v in kwargs.items():
        if hasattr(test, k):
            setattr(test, k, v)
    db.flush()
    return test


def finalize_test(db: Session, test_id: int) -> ControlTest | None:
    """Transition IN_PROGRESS → COMPLETED. Sets test_date, triggers next_test_date recalc."""
    test = db.query(ControlTest).filter(ControlTest.id == test_id).first()
    if not test or test.status != TEST_STATUS_IN_PROGRESS:
        return None
    test.status = TEST_STATUS_COMPLETED
    test.test_date = datetime.utcnow()
    db.flush()
    impl = db.query(ControlImplementation).filter(
        ControlImplementation.id == test.implementation_id
    ).first()
    update_next_test_date(db, impl)
    return test


def get_scheduled_tests(db: Session):
    """All scheduled (not yet started) tests for org-level implementations."""
    return db.query(ControlTest).options(
        joinedload(ControlTest.tester),
        joinedload(ControlTest.implementation).joinedload(ControlImplementation.control),
        joinedload(ControlTest.implementation).joinedload(ControlImplementation.owner),
    ).join(
        ControlImplementation, ControlTest.implementation_id == ControlImplementation.id
    ).filter(
        ControlTest.status == TEST_STATUS_SCHEDULED,
        ControlImplementation.vendor_id == None,
    ).order_by(ControlTest.scheduled_date.asc()).all()


def get_in_progress_tests(db: Session):
    """All in-progress tests for org-level implementations."""
    return db.query(ControlTest).options(
        joinedload(ControlTest.tester),
        joinedload(ControlTest.evidence_files),
        joinedload(ControlTest.implementation).joinedload(ControlImplementation.control),
        joinedload(ControlTest.implementation).joinedload(ControlImplementation.owner),
    ).join(
        ControlImplementation, ControlTest.implementation_id == ControlImplementation.id
    ).filter(
        ControlTest.status == TEST_STATUS_IN_PROGRESS,
        ControlImplementation.vendor_id == None,
    ).order_by(ControlTest.created_at.desc()).all()


def set_implementation_next_test_date(db: Session, impl_id: int, date: datetime | None):
    """Manually override the next_test_date on an implementation."""
    impl = db.query(ControlImplementation).filter(ControlImplementation.id == impl_id).first()
    if impl:
        impl.next_test_date = date
        return impl
    return None


def submit_test_review(db: Session, test_id: int, reviewer_user_id: int, review_notes: str = "") -> ControlTest | None:
    """Sign off on a test as a reviewer."""
    test = db.query(ControlTest).filter(ControlTest.id == test_id).first()
    if not test:
        return None
    test.reviewer_user_id = reviewer_user_id
    test.review_date = datetime.utcnow()
    test.review_notes = review_notes
    db.flush()
    return test


# ==================== CONTROL EVIDENCE ====================

EVIDENCE_UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "uploads", "control_evidence")


async def store_control_evidence(file, test_id: int) -> ControlEvidence:
    upload_dir = os.path.join(EVIDENCE_UPLOAD_DIR, str(test_id))
    os.makedirs(upload_dir, exist_ok=True)
    ext = os.path.splitext(file.filename)[1] if file.filename else ""
    stored_name = f"{uuid.uuid4().hex}{ext}"
    stored_path = os.path.join(upload_dir, stored_name)
    content = await file.read()
    with open(stored_path, "wb") as f:
        f.write(content)
    return ControlEvidence(
        test_id=test_id,
        original_filename=file.filename or "unknown",
        stored_filename=stored_name,
        stored_path=stored_path,
        content_type=file.content_type,
        size_bytes=len(content),
    )


def get_evidence(db: Session, evidence_id: int):
    return db.query(ControlEvidence).filter(ControlEvidence.id == evidence_id).first()


def delete_evidence(db: Session, evidence_id: int) -> bool:
    ev = db.query(ControlEvidence).filter(ControlEvidence.id == evidence_id).first()
    if not ev:
        return False
    if os.path.exists(ev.stored_path):
        os.remove(ev.stored_path)
    db.delete(ev)
    return True


# ==================== CONTROL FINDINGS ====================

def create_finding(db: Session, test_id: int, finding_type: str, severity: str,
                   criteria: str = None, condition: str = None, cause: str = None,
                   effect: str = None, recommendation: str = None,
                   owner_user_id: int = None, due_date=None) -> ControlFinding:
    """Create a new finding linked to a control test."""
    finding = ControlFinding(
        control_test_id=test_id,
        finding_type=finding_type,
        severity=severity,
        status=FINDING_STATUS_OPEN,
        criteria=criteria,
        condition=condition,
        cause=cause,
        effect=effect,
        recommendation=recommendation,
        owner_user_id=owner_user_id,
        due_date=due_date,
    )
    db.add(finding)
    db.flush()
    return finding


def update_finding(db: Session, finding_id: int, **kwargs) -> ControlFinding | None:
    """Update a finding's fields."""
    finding = db.query(ControlFinding).filter(ControlFinding.id == finding_id).first()
    if not finding:
        return None
    for k, v in kwargs.items():
        if hasattr(finding, k):
            setattr(finding, k, v)
    db.flush()
    return finding


def close_finding(db: Session, finding_id: int) -> ControlFinding | None:
    """Close a finding — sets status to CLOSED and records closed_date."""
    finding = db.query(ControlFinding).filter(ControlFinding.id == finding_id).first()
    if not finding:
        return None
    finding.status = FINDING_STATUS_CLOSED
    finding.closed_date = datetime.utcnow()
    db.flush()
    return finding


def get_finding(db: Session, finding_id: int) -> ControlFinding | None:
    """Get a single finding by ID with related objects."""
    return db.query(ControlFinding).options(
        joinedload(ControlFinding.test).joinedload(ControlTest.implementation).joinedload(ControlImplementation.control),
        joinedload(ControlFinding.owner),
        joinedload(ControlFinding.remediation_item),
    ).filter(ControlFinding.id == finding_id).first()


def get_test_findings(db: Session, test_id: int) -> list:
    """Get all findings for a specific test."""
    return db.query(ControlFinding).options(
        joinedload(ControlFinding.owner),
        joinedload(ControlFinding.remediation_item),
    ).filter(
        ControlFinding.control_test_id == test_id
    ).order_by(ControlFinding.created_at.desc()).all()


def get_open_findings(db: Session) -> list:
    """Get all open/in-progress findings for org-level implementations."""
    from models import FINDING_STATUS_IN_PROGRESS
    return db.query(ControlFinding).options(
        joinedload(ControlFinding.test).joinedload(ControlTest.implementation).joinedload(ControlImplementation.control),
        joinedload(ControlFinding.owner),
        joinedload(ControlFinding.remediation_item),
    ).join(
        ControlTest, ControlFinding.control_test_id == ControlTest.id
    ).join(
        ControlImplementation, ControlTest.implementation_id == ControlImplementation.id
    ).filter(
        ControlImplementation.vendor_id == None,
        ControlFinding.status.in_([FINDING_STATUS_OPEN, FINDING_STATUS_IN_PROGRESS]),
    ).order_by(ControlFinding.created_at.desc()).all()


# ==================== ROLL-FORWARD TESTING ====================

def roll_forward_test(db: Session, source_test_id: int, tester_id: int) -> ControlTest:
    """Clone a completed test as a roll-forward — copies procedure, scope, and metadata
    from the source test. Sets is_roll_forward=True and parent_test_id=source.
    Returns the new test in IN_PROGRESS status.
    """
    source = db.query(ControlTest).filter(ControlTest.id == source_test_id).first()
    if not source:
        raise ValueError(f"Source test {source_test_id} not found")

    new_test = ControlTest(
        implementation_id=source.implementation_id,
        test_type=source.test_type,
        test_procedure=source.test_procedure,
        tester_user_id=tester_id,
        status=TEST_STATUS_IN_PROGRESS,
        result=TEST_RESULT_NOT_TESTED,
        test_period_start=source.test_period_start,
        test_period_end=source.test_period_end,
        sample_size=source.sample_size,
        population_size=source.population_size,
        is_roll_forward=True,
        parent_test_id=source.id,
    )
    db.add(new_test)
    db.flush()
    # No test_date yet — set when finalized
    new_test.test_date = None
    return new_test


# ==================== EVIDENCE LINKING (Feature 7) ====================

def link_evidence_to_implementation(db: Session, evidence_id: int, impl_id: int) -> ControlEvidence | None:
    """Link an existing evidence file directly to an implementation (decoupled from test)."""
    ev = db.query(ControlEvidence).filter(ControlEvidence.id == evidence_id).first()
    if not ev:
        return None
    ev.implementation_id = impl_id
    db.flush()
    return ev


def get_implementation_evidence(db: Session, impl_id: int) -> list:
    """Get evidence files directly linked to an implementation (not via test)."""
    return db.query(ControlEvidence).filter(
        ControlEvidence.implementation_id == impl_id
    ).order_by(ControlEvidence.uploaded_at.desc()).all()


def update_evidence_framework_tags(db: Session, evidence_id: int, tags_json: str) -> ControlEvidence | None:
    """Update the framework_tags JSON on an evidence file."""
    ev = db.query(ControlEvidence).filter(ControlEvidence.id == evidence_id).first()
    if not ev:
        return None
    ev.framework_tags = tags_json
    db.flush()
    return ev


async def store_implementation_evidence(file, impl_id: int) -> ControlEvidence:
    """Upload evidence directly to an implementation (not tied to a specific test)."""
    upload_dir = os.path.join(EVIDENCE_UPLOAD_DIR, f"impl_{impl_id}")
    os.makedirs(upload_dir, exist_ok=True)
    ext = os.path.splitext(file.filename)[1] if file.filename else ""
    stored_name = f"{uuid.uuid4().hex}{ext}"
    stored_path = os.path.join(upload_dir, stored_name)
    content = await file.read()
    with open(stored_path, "wb") as f:
        f.write(content)
    return ControlEvidence(
        implementation_id=impl_id,
        original_filename=file.filename or "unknown",
        stored_filename=stored_name,
        stored_path=stored_path,
        content_type=file.content_type,
        size_bytes=len(content),
    )


# ==================== TEST RESULTS TIMELINE (Feature 9) ====================

def get_test_results_timeline(db: Session, months: int = 12) -> list:
    """Monthly aggregation of test results for org-level implementations.
    Returns list of dicts: [{month: 'YYYY-MM', pass_count, fail_count, partial_count, total}]
    """
    from sqlalchemy import func as sa_func, extract, case
    from models import TEST_RESULT_PASS, TEST_RESULT_FAIL, TEST_RESULT_PARTIAL

    now = datetime.utcnow()
    start = datetime(now.year, now.month, 1) - timedelta(days=30 * (months - 1))

    rows = db.query(
        sa_func.strftime('%Y-%m', ControlTest.test_date).label('month'),
        sa_func.sum(case((ControlTest.result == TEST_RESULT_PASS, 1), else_=0)).label('pass_count'),
        sa_func.sum(case((ControlTest.result == TEST_RESULT_FAIL, 1), else_=0)).label('fail_count'),
        sa_func.sum(case((ControlTest.result == TEST_RESULT_PARTIAL, 1), else_=0)).label('partial_count'),
        sa_func.count(ControlTest.id).label('total'),
    ).join(
        ControlImplementation, ControlTest.implementation_id == ControlImplementation.id
    ).filter(
        ControlTest.status == TEST_STATUS_COMPLETED,
        ControlTest.test_date != None,
        ControlTest.test_date >= start,
        ControlImplementation.vendor_id == None,
    ).group_by(
        sa_func.strftime('%Y-%m', ControlTest.test_date)
    ).order_by(
        sa_func.strftime('%Y-%m', ControlTest.test_date)
    ).all()

    return [
        {
            "month": r.month,
            "pass_count": r.pass_count or 0,
            "fail_count": r.fail_count or 0,
            "partial_count": r.partial_count or 0,
            "total": r.total or 0,
        }
        for r in rows
    ]
