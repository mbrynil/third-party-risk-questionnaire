"""Audit trail service — append-only logging of all state changes."""

import json
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import desc

from models import AuditLog, User


def log_audit(
    db: Session,
    action: str,
    entity_type: str,
    entity_id: int | None = None,
    entity_label: str | None = None,
    old_value: dict | str | None = None,
    new_value: dict | str | None = None,
    description: str | None = None,
    actor_user: User | None = None,
    ip_address: str | None = None,
):
    """Create an audit log entry. Does NOT commit — caller must commit.

    Same contract as log_activity: the caller owns the transaction.
    """
    actor_user_id = actor_user.id if actor_user else None
    actor_email = actor_user.email if actor_user else None

    old_json = json.dumps(old_value) if isinstance(old_value, (dict, list)) else old_value
    new_json = json.dumps(new_value) if isinstance(new_value, (dict, list)) else new_value

    entry = AuditLog(
        timestamp=datetime.utcnow(),
        actor_user_id=actor_user_id,
        actor_email=actor_email,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_label=entity_label,
        old_value=old_json,
        new_value=new_json,
        description=description,
        ip_address=ip_address,
    )
    db.add(entry)
    return entry


def get_audit_page(
    db: Session,
    entity_type: str | None = None,
    actor_user_id: int | None = None,
    action: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list, int]:
    """Return paginated audit records with optional filters.

    Returns (records, total_count).
    """
    query = db.query(AuditLog)

    if entity_type:
        query = query.filter(AuditLog.entity_type == entity_type)
    if actor_user_id:
        query = query.filter(AuditLog.actor_user_id == actor_user_id)
    if action:
        query = query.filter(AuditLog.action == action)
    if date_from:
        query = query.filter(AuditLog.timestamp >= date_from)
    if date_to:
        query = query.filter(AuditLog.timestamp <= date_to)

    total = query.count()
    records = query.order_by(desc(AuditLog.timestamp)).offset(offset).limit(limit).all()

    return records, total
