"""Incident management service — CRUD, status workflow, timeline, mappings, stats."""

from datetime import datetime
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from models import (
    Incident, IncidentTimeline, IncidentControlMapping, IncidentRiskMapping,
    User,
    INCIDENT_STATUS_REPORTED, INCIDENT_STATUS_TRIAGED,
    INCIDENT_STATUS_INVESTIGATING, INCIDENT_STATUS_CONTAINED,
    INCIDENT_STATUS_RESOLVED, INCIDENT_STATUS_CLOSED,
    VALID_INCIDENT_STATUSES, INCIDENT_STATUS_LABELS, INCIDENT_STATUS_COLORS,
    VALID_INCIDENT_SEVERITIES, INCIDENT_SEVERITY_LABELS, INCIDENT_SEVERITY_COLORS,
    VALID_INCIDENT_CATEGORIES, INCIDENT_CATEGORY_LABELS,
)

# Valid status transitions (current -> allowed next statuses)
_STATUS_TRANSITIONS = {
    INCIDENT_STATUS_REPORTED: [INCIDENT_STATUS_TRIAGED, INCIDENT_STATUS_CLOSED],
    INCIDENT_STATUS_TRIAGED: [INCIDENT_STATUS_INVESTIGATING, INCIDENT_STATUS_CLOSED],
    INCIDENT_STATUS_INVESTIGATING: [INCIDENT_STATUS_CONTAINED, INCIDENT_STATUS_RESOLVED, INCIDENT_STATUS_CLOSED],
    INCIDENT_STATUS_CONTAINED: [INCIDENT_STATUS_RESOLVED, INCIDENT_STATUS_CLOSED],
    INCIDENT_STATUS_RESOLVED: [INCIDENT_STATUS_CLOSED],
    INCIDENT_STATUS_CLOSED: [],
}


def generate_incident_ref(db: Session) -> str:
    """Auto-generate INC-### reference."""
    existing = db.query(Incident.incident_ref).all()
    max_num = 0
    for (ref,) in existing:
        try:
            num = int(ref.split("-")[-1])
            if num > max_num:
                max_num = num
        except (ValueError, IndexError):
            pass
    return f"INC-{max_num + 1:03d}"


def get_all_incidents(db: Session, status=None, severity=None, category=None, lead_id=None):
    """Return filtered list of active incidents with eager loads."""
    q = db.query(Incident).filter(Incident.is_active == True)
    if status:
        q = q.filter(Incident.status == status)
    if severity:
        q = q.filter(Incident.severity == severity)
    if category:
        q = q.filter(Incident.category == category)
    if lead_id:
        q = q.filter(Incident.response_lead_user_id == lead_id)
    return q.options(
        joinedload(Incident.response_lead),
        joinedload(Incident.vendor),
    ).order_by(Incident.reported_at.desc()).all()


def get_incident(db: Session, incident_id: int):
    """Return single incident with all relationships eagerly loaded."""
    return db.query(Incident).options(
        joinedload(Incident.response_lead),
        joinedload(Incident.vendor),
        joinedload(Incident.timeline_entries).joinedload(IncidentTimeline.user),
        joinedload(Incident.control_mappings).joinedload(IncidentControlMapping.control),
        joinedload(Incident.risk_mappings).joinedload(IncidentRiskMapping.risk),
    ).filter(Incident.id == incident_id).first()


def create_incident(db: Session, **kwargs):
    """Create a new incident with auto-generated ref and initial timeline entry."""
    incident_ref = generate_incident_ref(db)
    incident = Incident(
        incident_ref=incident_ref,
        title=kwargs.get("title", ""),
        description=kwargs.get("description"),
        category=kwargs.get("category"),
        severity=kwargs.get("severity", "P3"),
        status=INCIDENT_STATUS_REPORTED,
        detected_at=kwargs.get("detected_at"),
        reported_at=kwargs.get("reported_at") or datetime.utcnow(),
        detection_method=kwargs.get("detection_method"),
        affected_systems=kwargs.get("affected_systems"),
        affected_users_count=kwargs.get("affected_users_count", 0),
        data_compromised=kwargs.get("data_compromised", False),
        business_impact=kwargs.get("business_impact"),
        response_lead_user_id=kwargs.get("response_lead_user_id"),
        root_cause=kwargs.get("root_cause"),
        lessons_learned=kwargs.get("lessons_learned"),
        corrective_actions=kwargs.get("corrective_actions"),
        vendor_id=kwargs.get("vendor_id"),
    )
    db.add(incident)
    db.flush()

    # Add initial timeline entry
    entry = IncidentTimeline(
        incident_id=incident.id,
        event_at=datetime.utcnow(),
        event_type="CREATED",
        description="Incident reported",
        user_id=kwargs.get("created_by_user_id"),
    )
    db.add(entry)
    db.flush()

    return incident


def update_incident(db: Session, incident_id: int, **kwargs):
    """Update incident fields."""
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        return None
    for k, v in kwargs.items():
        if hasattr(incident, k):
            setattr(incident, k, v)
    db.flush()
    return incident


def delete_incident(db: Session, incident_id: int):
    """Soft-delete an incident."""
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        return False
    incident.is_active = False
    db.flush()
    return True


def update_status(db: Session, incident_id: int, new_status: str, user_id=None, notes=None):
    """Transition incident status, set timestamp fields, add timeline entry.

    Returns (incident, error_message). error_message is None on success.
    """
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        return None, "Incident not found"

    # Validate transition
    allowed = _STATUS_TRANSITIONS.get(incident.status, [])
    if new_status not in allowed:
        return incident, f"Cannot transition from {incident.status} to {new_status}"

    old_status = incident.status
    incident.status = new_status

    # Set timestamp fields
    now = datetime.utcnow()
    if new_status == INCIDENT_STATUS_CONTAINED:
        incident.contained_at = now
    elif new_status == INCIDENT_STATUS_RESOLVED:
        incident.resolved_at = now
    elif new_status == INCIDENT_STATUS_CLOSED:
        incident.closed_at = now

    # Add timeline entry
    description = f"Status changed from {INCIDENT_STATUS_LABELS.get(old_status, old_status)} to {INCIDENT_STATUS_LABELS.get(new_status, new_status)}"
    if notes:
        description += f" — {notes}"
    entry = IncidentTimeline(
        incident_id=incident_id,
        event_at=now,
        event_type="STATUS_CHANGE",
        description=description,
        user_id=user_id,
    )
    db.add(entry)
    db.flush()

    return incident, None


def add_timeline_entry(db: Session, incident_id: int, event_type: str, description: str, user_id=None):
    """Add a timeline entry to an incident."""
    entry = IncidentTimeline(
        incident_id=incident_id,
        event_at=datetime.utcnow(),
        event_type=event_type,
        description=description,
        user_id=user_id,
    )
    db.add(entry)
    db.flush()
    return entry


def set_control_mappings(db: Session, incident_id: int, control_ids: list, relationship_type: str = "FAILED"):
    """Replace all control mappings for an incident."""
    db.query(IncidentControlMapping).filter(IncidentControlMapping.incident_id == incident_id).delete()
    for cid in control_ids:
        db.add(IncidentControlMapping(
            incident_id=incident_id,
            control_id=cid,
            relationship_type=relationship_type,
        ))
    db.flush()


def set_risk_mappings(db: Session, incident_id: int, risk_ids: list):
    """Replace all risk mappings for an incident."""
    db.query(IncidentRiskMapping).filter(IncidentRiskMapping.incident_id == incident_id).delete()
    for rid in risk_ids:
        db.add(IncidentRiskMapping(incident_id=incident_id, risk_id=rid))
    db.flush()


def get_incident_stats(db: Session) -> dict:
    """Return summary statistics for incidents."""
    all_incidents = db.query(Incident).filter(Incident.is_active == True).all()
    total = len(all_incidents)

    by_status = {}
    for s in VALID_INCIDENT_STATUSES:
        by_status[s] = 0
    for inc in all_incidents:
        by_status[inc.status] = by_status.get(inc.status, 0) + 1

    by_severity = {}
    for s in VALID_INCIDENT_SEVERITIES:
        by_severity[s] = 0
    for inc in all_incidents:
        by_severity[inc.severity] = by_severity.get(inc.severity, 0) + 1

    open_count = sum(1 for inc in all_incidents if inc.status not in (INCIDENT_STATUS_RESOLVED, INCIDENT_STATUS_CLOSED))

    # Mean time to resolve (days) for resolved/closed incidents
    resolved = [inc for inc in all_incidents if inc.resolved_at and inc.reported_at]
    if resolved:
        total_days = sum((inc.resolved_at - inc.reported_at).total_seconds() / 86400 for inc in resolved)
        mttr_days = round(total_days / len(resolved), 1)
    else:
        mttr_days = None

    return {
        "total": total,
        "by_status": by_status,
        "by_severity": by_severity,
        "open_count": open_count,
        "mttr_days": mttr_days,
    }


def get_incident_dashboard_data(db: Session) -> dict:
    """Return KPIs, chart data, and recent incidents for the dashboard."""
    stats = get_incident_stats(db)

    all_incidents = db.query(Incident).options(
        joinedload(Incident.response_lead),
        joinedload(Incident.vendor),
    ).filter(Incident.is_active == True).order_by(Incident.reported_at.desc()).all()

    # Category breakdown
    by_category = {}
    for cat in VALID_INCIDENT_CATEGORIES:
        by_category[cat] = 0
    for inc in all_incidents:
        if inc.category:
            by_category[inc.category] = by_category.get(inc.category, 0) + 1

    # Recent incidents (last 10)
    recent = all_incidents[:10]

    return {
        **stats,
        "by_category": by_category,
        "recent_incidents": recent,
        "status_labels": INCIDENT_STATUS_LABELS,
        "status_colors": INCIDENT_STATUS_COLORS,
        "severity_labels": INCIDENT_SEVERITY_LABELS,
        "severity_colors": INCIDENT_SEVERITY_COLORS,
        "category_labels": INCIDENT_CATEGORY_LABELS,
    }
