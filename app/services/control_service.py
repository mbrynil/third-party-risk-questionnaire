"""Control library service — CRUD for controls, implementations, testing, and evidence."""

import os
import uuid
from datetime import datetime, timedelta
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from models import (
    Control, ControlFrameworkMapping, ControlQuestionMapping, ControlRiskMapping,
    ControlImplementation, ControlTest, ControlEvidence,
    IMPL_STATUS_NOT_IMPLEMENTED, IMPL_STATUS_IMPLEMENTED,
    CONTROL_FREQUENCY_DAYS,
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


def get_implementation(db: Session, impl_id: int):
    return db.query(ControlImplementation).options(
        joinedload(ControlImplementation.control).joinedload(Control.framework_mappings),
        joinedload(ControlImplementation.vendor),
        joinedload(ControlImplementation.owner),
        joinedload(ControlImplementation.tests).joinedload(ControlTest.tester),
    ).filter(ControlImplementation.id == impl_id).first()


def create_implementation(db: Session, control_id: int, vendor_id: int, **kwargs) -> ControlImplementation:
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


# ==================== CONTROL TESTING ====================

def create_test(db: Session, impl_id: int, test_type: str, procedure: str,
                tester_id: int | None, result: str, findings: str, recommendations: str) -> ControlTest:
    test = ControlTest(
        implementation_id=impl_id,
        test_type=test_type,
        test_procedure=procedure,
        tester_user_id=tester_id,
        result=result,
        findings=findings,
        recommendations=recommendations,
        test_date=datetime.utcnow(),
    )
    db.add(test)
    db.flush()
    update_next_test_date(db, db.query(ControlImplementation).filter(
        ControlImplementation.id == impl_id).first())
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
        joinedload(ControlTest.evidence_files),
        joinedload(ControlTest.implementation).joinedload(ControlImplementation.control),
        joinedload(ControlTest.implementation).joinedload(ControlImplementation.vendor),
    ).filter(ControlTest.id == test_id).first()


def get_overdue_tests(db: Session):
    now = datetime.utcnow()
    return db.query(ControlImplementation).options(
        joinedload(ControlImplementation.control),
        joinedload(ControlImplementation.vendor),
    ).filter(
        ControlImplementation.next_test_date < now,
        ControlImplementation.status == IMPL_STATUS_IMPLEMENTED,
    ).all()


def get_upcoming_tests(db: Session, days: int = 30):
    now = datetime.utcnow()
    threshold = now + timedelta(days=days)
    return db.query(ControlImplementation).options(
        joinedload(ControlImplementation.control),
        joinedload(ControlImplementation.vendor),
    ).filter(
        ControlImplementation.next_test_date >= now,
        ControlImplementation.next_test_date <= threshold,
        ControlImplementation.status == IMPL_STATUS_IMPLEMENTED,
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
    """All IMPLEMENTED control implementations — the testing obligation backlog."""
    return db.query(ControlImplementation).options(
        joinedload(ControlImplementation.control),
        joinedload(ControlImplementation.vendor),
        joinedload(ControlImplementation.owner),
    ).filter(
        ControlImplementation.status == IMPL_STATUS_IMPLEMENTED,
    ).order_by(
        ControlImplementation.next_test_date.asc().nullsfirst(),
    ).all()


def get_all_test_history(db: Session, limit: int = 200):
    """Most recent test executions across all implementations."""
    return db.query(ControlTest).options(
        joinedload(ControlTest.tester),
        joinedload(ControlTest.evidence_files),
        joinedload(ControlTest.implementation).joinedload(ControlImplementation.control),
        joinedload(ControlTest.implementation).joinedload(ControlImplementation.vendor),
    ).order_by(ControlTest.test_date.desc()).limit(limit).all()


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
