"""Control dashboard service — aggregations for gap analysis and executive views."""

from datetime import datetime
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from models import (
    Control, ControlFrameworkMapping, ControlImplementation, ControlTest,
    FrameworkRequirement,
    AVAILABLE_FRAMEWORKS, FRAMEWORK_DISPLAY, VALID_CONTROL_DOMAINS, SEEDED_FRAMEWORKS,
    IMPL_STATUS_IMPLEMENTED, IMPL_STATUS_PARTIAL, IMPL_STATUS_NOT_APPLICABLE,
    EFFECTIVENESS_EFFECTIVE, EFFECTIVENESS_LARGELY_EFFECTIVE,
    TEST_RESULT_PASS, TEST_RESULT_FAIL,
)


def get_framework_coverage(db: Session, vendor_id: int | None = None) -> dict:
    """Per-framework coverage stats.
    For seeded frameworks: total = requirement count (canonical catalog).
    For others: total = mapped controls (legacy behavior).
    """
    result = {}
    for fw_key, fw_label in AVAILABLE_FRAMEWORKS:
        # Check if this framework has seeded requirements
        req_count = 0
        if fw_key in SEEDED_FRAMEWORKS:
            req_count = db.query(FrameworkRequirement).filter(
                FrameworkRequirement.framework == fw_key,
                FrameworkRequirement.is_active == True,
            ).count()

        mappings = db.query(ControlFrameworkMapping).filter(
            ControlFrameworkMapping.framework == fw_key
        ).all()
        control_ids = list({m.control_id for m in mappings})
        if not control_ids and req_count == 0:
            continue

        # Use requirement count as total for seeded frameworks, else mapped controls
        if req_count > 0:
            total = req_count
        else:
            active_controls = db.query(Control).filter(
                Control.id.in_(control_ids), Control.is_active == True
            ).all()
            active_ids = [c.id for c in active_controls]
            total = len(active_ids)
            if total == 0:
                continue

        # Get active control IDs for implementation stats
        active_controls = db.query(Control).filter(
            Control.id.in_(control_ids), Control.is_active == True
        ).all() if control_ids else []
        active_ids = [c.id for c in active_controls]

        if vendor_id:
            impls = db.query(ControlImplementation).filter(
                ControlImplementation.vendor_id == vendor_id,
                ControlImplementation.control_id.in_(active_ids),
            ).all() if active_ids else []
        else:
            impls = db.query(ControlImplementation).filter(
                ControlImplementation.control_id.in_(active_ids),
                ControlImplementation.vendor_id == None,
            ).all() if active_ids else []

        impl_control_ids = set()
        effective_control_ids = set()
        for impl in impls:
            if impl.status in (IMPL_STATUS_IMPLEMENTED, IMPL_STATUS_PARTIAL):
                impl_control_ids.add(impl.control_id)
            if impl.effectiveness in (EFFECTIVENESS_EFFECTIVE, EFFECTIVENESS_LARGELY_EFFECTIVE):
                effective_control_ids.add(impl.control_id)

        implemented = len(impl_control_ids)
        effective = len(effective_control_ids)

        result[fw_key] = {
            "label": fw_label,
            "total": total,
            "implemented": implemented,
            "effective": effective,
            "coverage_pct": round(implemented / total * 100) if total > 0 else 0,
            "effectiveness_pct": round(effective / total * 100) if total > 0 else 0,
        }
    return result


def get_domain_effectiveness_heatmap(db: Session, vendor_id: int | None = None) -> list:
    """Per-domain effectiveness heatmap data."""
    result = []
    for domain in VALID_CONTROL_DOMAINS:
        controls = db.query(Control).filter(
            Control.domain == domain, Control.is_active == True
        ).all()
        if not controls:
            continue
        control_ids = [c.id for c in controls]
        total = len(control_ids)

        q = db.query(ControlImplementation).filter(
            ControlImplementation.control_id.in_(control_ids),
        )
        if vendor_id:
            q = q.filter(ControlImplementation.vendor_id == vendor_id)
        else:
            q = q.filter(ControlImplementation.vendor_id == None)
        impls = q.all()

        implemented = sum(1 for i in impls if i.status == IMPL_STATUS_IMPLEMENTED)
        effective = sum(1 for i in impls if i.effectiveness in (EFFECTIVENESS_EFFECTIVE, EFFECTIVENESS_LARGELY_EFFECTIVE))

        pct = round(effective / total * 100) if total > 0 else 0
        if pct >= 80:
            color = "#198754"
        elif pct >= 60:
            color = "#20c997"
        elif pct >= 40:
            color = "#ffc107"
        elif pct >= 20:
            color = "#fd7e14"
        else:
            color = "#dc3545"

        result.append({
            "domain": domain,
            "total": total,
            "implemented": implemented,
            "effective": effective,
            "pct": pct,
            "color": color,
        })
    return result


def get_testing_status_summary(db: Session) -> dict:
    now = datetime.utcnow()
    year_start = datetime(now.year, 1, 1)
    tests_ytd = db.query(ControlTest).join(
        ControlImplementation, ControlTest.implementation_id == ControlImplementation.id
    ).filter(
        ControlTest.test_date >= year_start,
        ControlImplementation.vendor_id == None,
    ).all()
    total = len(tests_ytd)
    passed = sum(1 for t in tests_ytd if t.result == TEST_RESULT_PASS)
    failed = sum(1 for t in tests_ytd if t.result == TEST_RESULT_FAIL)

    overdue = db.query(ControlImplementation).filter(
        ControlImplementation.next_test_date < now,
        ControlImplementation.status == IMPL_STATUS_IMPLEMENTED,
        ControlImplementation.vendor_id == None,
    ).count()

    from app.services.control_service import get_upcoming_tests
    upcoming = len(get_upcoming_tests(db, days=30))

    return {
        "total_ytd": total,
        "pass": passed,
        "fail": failed,
        "overdue": overdue,
        "upcoming": upcoming,
    }


def get_control_dashboard_data(db: Session) -> dict:
    active = db.query(Control).filter(Control.is_active == True).count()

    all_impls = db.query(ControlImplementation).filter(
        ControlImplementation.vendor_id == None
    ).all()
    total_impls = len(all_impls)
    impl_count = sum(1 for i in all_impls if i.status == IMPL_STATUS_IMPLEMENTED)
    eff_count = sum(1 for i in all_impls if i.effectiveness in (EFFECTIVENESS_EFFECTIVE, EFFECTIVENESS_LARGELY_EFFECTIVE))
    applicable = sum(1 for i in all_impls if i.status != IMPL_STATUS_NOT_APPLICABLE)

    impl_pct = round(impl_count / applicable * 100) if applicable > 0 else 0
    eff_pct = round(eff_count / applicable * 100) if applicable > 0 else 0

    fw_coverage = get_framework_coverage(db)
    domain_heatmap = get_domain_effectiveness_heatmap(db)
    testing = get_testing_status_summary(db)

    # Recent tests
    recent_tests = db.query(ControlTest).options(
        joinedload(ControlTest.tester),
        joinedload(ControlTest.implementation).joinedload(ControlImplementation.control),
        joinedload(ControlTest.implementation).joinedload(ControlImplementation.owner),
    ).join(
        ControlImplementation, ControlTest.implementation_id == ControlImplementation.id
    ).filter(
        ControlImplementation.vendor_id == None,
    ).order_by(ControlTest.test_date.desc()).limit(10).all()

    return {
        "kpis": {
            "active_controls": active,
            "impl_pct": impl_pct,
            "eff_pct": eff_pct,
            "overdue_tests": testing["overdue"],
            "frameworks_covered": len(fw_coverage),
        },
        "fw_coverage": fw_coverage,
        "domain_heatmap": domain_heatmap,
        "testing": testing,
        "recent_tests": recent_tests,
    }


def get_vendor_gap_analysis(db: Session, vendor_id: int, framework_key: str | None = None) -> list:
    """Per-vendor gap analysis: each active control with vendor's impl status."""
    q = db.query(Control).options(
        joinedload(Control.framework_mappings),
    ).filter(Control.is_active == True)

    if framework_key:
        mapped_ids = [m.control_id for m in db.query(ControlFrameworkMapping).filter(
            ControlFrameworkMapping.framework == framework_key
        ).all()]
        if mapped_ids:
            q = q.filter(Control.id.in_(mapped_ids))
        else:
            return []

    controls = q.order_by(Control.domain, Control.control_ref).all()
    control_ids = [c.id for c in controls]

    impls = db.query(ControlImplementation).filter(
        ControlImplementation.vendor_id == vendor_id,
        ControlImplementation.control_id.in_(control_ids),
    ).all() if control_ids else []
    impl_map = {i.control_id: i for i in impls}

    gaps = []
    for c in controls:
        impl = impl_map.get(c.id)
        gaps.append({
            "control": c,
            "implementation": impl,
            "status": impl.status if impl else "NOT_TRACKED",
            "effectiveness": impl.effectiveness if impl else "NONE",
            "is_gap": impl is None or impl.status not in (IMPL_STATUS_IMPLEMENTED, IMPL_STATUS_NOT_APPLICABLE),
        })
    return gaps
