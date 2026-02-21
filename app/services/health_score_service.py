"""Control Health Score service — computes a 0-100 health score per ControlImplementation."""

from datetime import datetime
from sqlalchemy.orm import Session

from models import (
    ControlImplementation, ControlTest, ControlEvidence, ControlFinding,
    ControlHealthSnapshot,
    IMPL_STATUS_IMPLEMENTED, IMPL_STATUS_PARTIAL, IMPL_STATUS_PLANNED,
    IMPL_STATUS_NOT_IMPLEMENTED, IMPL_STATUS_NOT_APPLICABLE,
    CONTROL_FREQUENCY_DAYS,
    TEST_STATUS_COMPLETED,
    FINDING_STATUS_OPEN, FINDING_STATUS_IN_PROGRESS,
)


# ---------------------------------------------------------------------------
# Health label thresholds
# ---------------------------------------------------------------------------

def get_health_label(score: int) -> tuple[str, str]:
    """Returns (label, color) for a score.
    Healthy(80+)=#198754, Adequate(60-79)=#0dcaf0, At Risk(40-59)=#fd7e14, Critical(<40)=#dc3545
    """
    if score >= 80:
        return ("Healthy", "#198754")
    elif score >= 60:
        return ("Adequate", "#0dcaf0")
    elif score >= 40:
        return ("At Risk", "#fd7e14")
    else:
        return ("Critical", "#dc3545")


# ---------------------------------------------------------------------------
# Factor 1: Testing Recency (0-25 pts)
# ---------------------------------------------------------------------------

def _score_testing_recency(db: Session, impl: ControlImplementation) -> int:
    """25 if tested on time, 0 if never tested, sliding scale based on how overdue."""
    # Get the most recent completed test
    latest_test = db.query(ControlTest).filter(
        ControlTest.implementation_id == impl.id,
        ControlTest.status == TEST_STATUS_COMPLETED,
        ControlTest.test_date != None,
    ).order_by(ControlTest.test_date.desc()).first()

    if not latest_test or not latest_test.test_date:
        return 0

    # Determine the required frequency in days
    freq_days = CONTROL_FREQUENCY_DAYS.get(
        impl.control.test_frequency if impl.control else None, 365
    )

    now = datetime.utcnow()
    days_since_test = (now - latest_test.test_date).days

    if days_since_test <= freq_days:
        # Tested within required frequency — full marks
        return 25

    # How far overdue as a ratio
    overdue_days = days_since_test - freq_days
    # Give a grace period of the same length as the frequency — after 2x, score = 0
    overdue_ratio = min(overdue_days / max(freq_days, 1), 1.0)
    score = int(25 * (1 - overdue_ratio))
    return max(score, 0)


# ---------------------------------------------------------------------------
# Factor 2: Implementation Status (0-25 pts)
# ---------------------------------------------------------------------------

_IMPL_STATUS_POINTS = {
    IMPL_STATUS_IMPLEMENTED: 25,
    IMPL_STATUS_NOT_APPLICABLE: 25,
    IMPL_STATUS_PARTIAL: 15,
    IMPL_STATUS_PLANNED: 10,
    IMPL_STATUS_NOT_IMPLEMENTED: 0,
}


def _score_implementation_status(impl: ControlImplementation) -> int:
    return _IMPL_STATUS_POINTS.get(impl.status, 0)


# ---------------------------------------------------------------------------
# Factor 3: Evidence Freshness (0-20 pts)
# ---------------------------------------------------------------------------

def _score_evidence_freshness(db: Session, impl: ControlImplementation) -> int:
    """20 if evidence uploaded within last 90 days, sliding scale down to 0 at 365+ days."""
    # Get the most recent completed test
    latest_test = db.query(ControlTest).filter(
        ControlTest.implementation_id == impl.id,
        ControlTest.status == TEST_STATUS_COMPLETED,
    ).order_by(ControlTest.test_date.desc()).first()

    if not latest_test:
        return 0

    # Get the most recent evidence file for this test
    latest_evidence = db.query(ControlEvidence).filter(
        ControlEvidence.test_id == latest_test.id,
    ).order_by(ControlEvidence.uploaded_at.desc()).first()

    if not latest_evidence or not latest_evidence.uploaded_at:
        return 0

    now = datetime.utcnow()
    days_since_upload = (now - latest_evidence.uploaded_at).days

    if days_since_upload <= 90:
        return 20
    elif days_since_upload >= 365:
        return 0
    else:
        # Linear scale from 20 down to 0 between 90 and 365 days
        ratio = (days_since_upload - 90) / (365 - 90)
        return max(int(20 * (1 - ratio)), 0)


# ---------------------------------------------------------------------------
# Factor 4: Evidence Completeness (0-15 pts)
# ---------------------------------------------------------------------------

def _score_evidence_completeness(db: Session, impl: ControlImplementation) -> int:
    """15 if the latest completed test has evidence attached, 0 if not."""
    latest_test = db.query(ControlTest).filter(
        ControlTest.implementation_id == impl.id,
        ControlTest.status == TEST_STATUS_COMPLETED,
    ).order_by(ControlTest.test_date.desc()).first()

    if not latest_test:
        return 0

    evidence_count = db.query(ControlEvidence).filter(
        ControlEvidence.test_id == latest_test.id,
    ).count()

    return 15 if evidence_count > 0 else 0


# ---------------------------------------------------------------------------
# Factor 5: Open Findings (0-15 pts)
# ---------------------------------------------------------------------------

def _score_open_findings(db: Session, impl: ControlImplementation) -> int:
    """15 if no open findings, 0 if there are open findings.
    Uses the ControlFinding model linked through ControlTest.
    """
    # Check for open/in-progress findings on any test for this implementation
    open_count = db.query(ControlFinding).join(
        ControlTest, ControlFinding.control_test_id == ControlTest.id
    ).filter(
        ControlTest.implementation_id == impl.id,
        ControlFinding.status.in_([FINDING_STATUS_OPEN, FINDING_STATUS_IN_PROGRESS]),
    ).count()

    return 0 if open_count > 0 else 15


# ---------------------------------------------------------------------------
# Main compute functions
# ---------------------------------------------------------------------------

def compute_health_score(db: Session, impl: ControlImplementation) -> dict:
    """Returns {score: int, factors: {...}, health_label: str, health_color: str}"""
    testing = _score_testing_recency(db, impl)
    implementation = _score_implementation_status(impl)
    evidence_freshness = _score_evidence_freshness(db, impl)
    evidence_completeness = _score_evidence_completeness(db, impl)
    findings = _score_open_findings(db, impl)

    score = testing + implementation + evidence_freshness + evidence_completeness + findings
    label, color = get_health_label(score)

    return {
        "score": score,
        "factors": {
            "testing": testing,
            "implementation": implementation,
            "evidence_freshness": evidence_freshness,
            "evidence_completeness": evidence_completeness,
            "findings": findings,
        },
        "health_label": label,
        "health_color": color,
    }


def compute_readiness(db: Session, impl: ControlImplementation) -> dict:
    """Control Readiness: Returns readiness status for an implementation.
    {status: 'READY'|'PARTIAL'|'NOT_READY', has_owner: bool, has_evidence: bool, testing_current: bool}
    """
    # Check if implementation has an owner assigned
    has_owner = impl.owner_user_id is not None

    # Check if there is any evidence on the latest completed test
    latest_test = db.query(ControlTest).filter(
        ControlTest.implementation_id == impl.id,
        ControlTest.status == TEST_STATUS_COMPLETED,
    ).order_by(ControlTest.test_date.desc()).first()

    has_evidence = False
    testing_current = False

    if latest_test:
        evidence_count = db.query(ControlEvidence).filter(
            ControlEvidence.test_id == latest_test.id,
        ).count()
        has_evidence = evidence_count > 0

        # Check if testing is current (within required frequency)
        if latest_test.test_date and impl.control:
            freq_days = CONTROL_FREQUENCY_DAYS.get(impl.control.test_frequency, 365)
            days_since = (datetime.utcnow() - latest_test.test_date).days
            testing_current = days_since <= freq_days

    # Determine readiness status
    checks = [has_owner, has_evidence, testing_current]
    passing = sum(checks)

    if passing == 3:
        status = "READY"
    elif passing >= 1:
        status = "PARTIAL"
    else:
        status = "NOT_READY"

    return {
        "status": status,
        "has_owner": has_owner,
        "has_evidence": has_evidence,
        "testing_current": testing_current,
    }


def compute_health_scores_bulk(db: Session, implementations: list) -> dict:
    """Returns {impl_id: health_score_dict} for all implementations."""
    result = {}
    for impl in implementations:
        result[impl.id] = compute_health_score(db, impl)
    return result


# ---------------------------------------------------------------------------
# Health Snapshot Recording (Feature 11)
# ---------------------------------------------------------------------------

def record_health_snapshot(db: Session, impl: ControlImplementation) -> "ControlHealthSnapshot":
    """Record a point-in-time health snapshot for trend analysis."""
    health = compute_health_score(db, impl)
    snapshot = ControlHealthSnapshot(
        implementation_id=impl.id,
        health_score=health["score"],
        health_label=health["health_label"],
        testing_score=health["factors"]["testing"],
        implementation_score=health["factors"]["implementation"],
        evidence_freshness_score=health["factors"]["evidence_freshness"],
        evidence_completeness_score=health["factors"]["evidence_completeness"],
        findings_score=health["factors"]["findings"],
    )
    db.add(snapshot)
    db.flush()
    return snapshot


def record_all_health_snapshots(db: Session) -> int:
    """Record health snapshots for all org-level implementations. Returns count."""
    impls = db.query(ControlImplementation).filter(
        ControlImplementation.vendor_id == None
    ).all()
    count = 0
    for impl in impls:
        record_health_snapshot(db, impl)
        count += 1
    db.flush()
    return count


def get_health_trend(db: Session, impl_id: int, months: int = 12) -> list:
    """Get health score trend for a specific implementation.
    Returns list of dicts: [{date: datetime, score: int, label: str}]
    """
    from datetime import timedelta
    cutoff = datetime.utcnow() - timedelta(days=30 * months)
    snapshots = db.query(ControlHealthSnapshot).filter(
        ControlHealthSnapshot.implementation_id == impl_id,
        ControlHealthSnapshot.snapshot_date >= cutoff,
    ).order_by(ControlHealthSnapshot.snapshot_date.asc()).all()
    return [
        {
            "date": s.snapshot_date.strftime("%Y-%m-%d"),
            "score": s.health_score,
            "label": s.health_label or "",
        }
        for s in snapshots
    ]


def get_portfolio_health_trend(db: Session, months: int = 12) -> list:
    """Get average health score trend across all org-level implementations.
    Returns list of dicts: [{date: 'YYYY-MM-DD', avg_score: float}]
    """
    from datetime import timedelta
    from sqlalchemy import func as sa_func
    cutoff = datetime.utcnow() - timedelta(days=30 * months)
    rows = db.query(
        sa_func.date(ControlHealthSnapshot.snapshot_date).label('snap_date'),
        sa_func.avg(ControlHealthSnapshot.health_score).label('avg_score'),
    ).filter(
        ControlHealthSnapshot.snapshot_date >= cutoff,
    ).group_by(
        sa_func.date(ControlHealthSnapshot.snapshot_date)
    ).order_by(
        sa_func.date(ControlHealthSnapshot.snapshot_date)
    ).all()
    return [
        {"date": str(r.snap_date), "avg_score": round(r.avg_score or 0)}
        for r in rows
    ]
