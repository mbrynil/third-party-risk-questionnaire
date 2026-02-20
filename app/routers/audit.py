"""Audit log viewer — admin-only paginated viewer with filters and CSV export."""

import csv
import io
from datetime import datetime

from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy.orm import Session

from app import templates
from models import (
    get_db, User, VALID_AUDIT_ACTIONS,
    AUDIT_ENTITY_VENDOR, AUDIT_ENTITY_ASSESSMENT, AUDIT_ENTITY_DECISION,
    AUDIT_ENTITY_REMEDIATION, AUDIT_ENTITY_EXCEPTION, AUDIT_ENTITY_USER,
    AUDIT_ENTITY_SCORING_CONFIG, AUDIT_ENTITY_TIERING_RULE,
    AUDIT_ENTITY_REMINDER_CONFIG, AUDIT_ENTITY_SLA_CONFIG,
)
from app.services.audit_service import get_audit_page
from app.services.auth_service import require_role

router = APIRouter(prefix="/admin")

_admin_dep = require_role("admin")

ENTITY_TYPES = [
    AUDIT_ENTITY_VENDOR, AUDIT_ENTITY_ASSESSMENT, AUDIT_ENTITY_DECISION,
    AUDIT_ENTITY_REMEDIATION, AUDIT_ENTITY_EXCEPTION, AUDIT_ENTITY_USER,
    AUDIT_ENTITY_SCORING_CONFIG, AUDIT_ENTITY_TIERING_RULE,
    AUDIT_ENTITY_REMINDER_CONFIG, AUDIT_ENTITY_SLA_CONFIG,
]

PAGE_SIZE = 50


def _parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        return None


@router.get("/audit", response_class=HTMLResponse)
async def audit_log_page(
    request: Request,
    entity_type: str = Query("", alias="entity_type"),
    actor_user_id: str = Query("", alias="actor_user_id"),
    action: str = Query("", alias="action"),
    date_from: str = Query("", alias="date_from"),
    date_to: str = Query("", alias="date_to"),
    page: int = Query(1, ge=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(_admin_dep),
):
    offset = (page - 1) * PAGE_SIZE

    records, total = get_audit_page(
        db,
        entity_type=entity_type or None,
        actor_user_id=int(actor_user_id) if actor_user_id.strip().isdigit() else None,
        action=action or None,
        date_from=_parse_date(date_from),
        date_to=_parse_date(date_to),
        offset=offset,
        limit=PAGE_SIZE,
    )

    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)

    users = db.query(User).filter(User.is_active == True).order_by(User.display_name).all()

    return templates.TemplateResponse("audit_log.html", {
        "request": request,
        "records": records,
        "total": total,
        "page": page,
        "total_pages": total_pages,
        "page_size": PAGE_SIZE,
        "entity_types": ENTITY_TYPES,
        "actions": VALID_AUDIT_ACTIONS,
        "users": users,
        # Current filters (for form state)
        "f_entity_type": entity_type,
        "f_actor_user_id": actor_user_id,
        "f_action": action,
        "f_date_from": date_from,
        "f_date_to": date_to,
    })


@router.get("/audit.csv")
async def audit_log_csv(
    request: Request,
    entity_type: str = Query("", alias="entity_type"),
    actor_user_id: str = Query("", alias="actor_user_id"),
    action: str = Query("", alias="action"),
    date_from: str = Query("", alias="date_from"),
    date_to: str = Query("", alias="date_to"),
    db: Session = Depends(get_db),
    current_user: User = Depends(_admin_dep),
):
    records, _ = get_audit_page(
        db,
        entity_type=entity_type or None,
        actor_user_id=int(actor_user_id) if actor_user_id.strip().isdigit() else None,
        action=action or None,
        date_from=_parse_date(date_from),
        date_to=_parse_date(date_to),
        offset=0,
        limit=10000,
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Timestamp", "Actor", "Action", "Entity Type", "Entity ID", "Entity", "Description", "IP Address"])

    for r in records:
        writer.writerow([
            r.timestamp.strftime("%Y-%m-%d %H:%M:%S") if r.timestamp else "",
            r.actor_email or "System",
            r.action,
            r.entity_type,
            r.entity_id or "",
            r.entity_label or "",
            r.description or "",
            r.ip_address or "",
        ])

    filename = f"audit_log_{datetime.utcnow().strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
