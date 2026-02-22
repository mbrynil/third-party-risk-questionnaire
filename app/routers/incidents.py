"""Incident management module — CRUD, status workflow, timeline, control/risk mappings."""

from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from datetime import datetime

from app import templates
from models import (
    get_db, User, Vendor, Control, Risk,
    Incident, IncidentTimeline, IncidentControlMapping, IncidentRiskMapping,
    VALID_INCIDENT_SEVERITIES, INCIDENT_SEVERITY_LABELS, INCIDENT_SEVERITY_COLORS,
    VALID_INCIDENT_STATUSES, INCIDENT_STATUS_LABELS, INCIDENT_STATUS_COLORS,
    VALID_INCIDENT_CATEGORIES, INCIDENT_CATEGORY_LABELS,
    AUDIT_ACTION_CREATE, AUDIT_ACTION_UPDATE, AUDIT_ACTION_DELETE, AUDIT_ACTION_STATUS_CHANGE,
    AUDIT_ENTITY_INCIDENT,
)
from app.services.auth_service import require_role, require_login
from app.services.audit_service import log_audit
from app.services import incident_service as svc

router = APIRouter()
_analyst_dep = require_role("admin", "analyst")
_admin_dep = require_role("admin")


# ==================== INCIDENT LIST ====================

@router.get("/incidents", response_class=HTMLResponse)
async def incident_list(
    request: Request,
    status: str = None,
    severity: str = None,
    category: str = None,
    lead_id: int = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "analyst")),
):
    incidents = svc.get_all_incidents(db, status=status, severity=severity,
                                      category=category, lead_id=lead_id)
    users = db.query(User).filter(User.is_active == True).order_by(User.display_name).all()
    stats = svc.get_incident_stats(db)
    return templates.TemplateResponse("incident_list.html", {
        "request": request,
        "incidents": incidents,
        "users": users,
        "stats": stats,
        "filters": {"status": status, "severity": severity, "category": category, "lead_id": lead_id},
        "VALID_INCIDENT_STATUSES": VALID_INCIDENT_STATUSES,
        "INCIDENT_STATUS_LABELS": INCIDENT_STATUS_LABELS,
        "INCIDENT_STATUS_COLORS": INCIDENT_STATUS_COLORS,
        "VALID_INCIDENT_SEVERITIES": VALID_INCIDENT_SEVERITIES,
        "INCIDENT_SEVERITY_LABELS": INCIDENT_SEVERITY_LABELS,
        "INCIDENT_SEVERITY_COLORS": INCIDENT_SEVERITY_COLORS,
        "VALID_INCIDENT_CATEGORIES": VALID_INCIDENT_CATEGORIES,
        "INCIDENT_CATEGORY_LABELS": INCIDENT_CATEGORY_LABELS,
    })


# ==================== DASHBOARD ====================

@router.get("/incidents/dashboard", response_class=HTMLResponse)
async def incident_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_login),
):
    data = svc.get_incident_dashboard_data(db)
    return templates.TemplateResponse("incident_dashboard.html", {
        "request": request,
        "data": data,
        "VALID_INCIDENT_STATUSES": VALID_INCIDENT_STATUSES,
        "INCIDENT_STATUS_LABELS": INCIDENT_STATUS_LABELS,
        "INCIDENT_STATUS_COLORS": INCIDENT_STATUS_COLORS,
        "VALID_INCIDENT_SEVERITIES": VALID_INCIDENT_SEVERITIES,
        "INCIDENT_SEVERITY_LABELS": INCIDENT_SEVERITY_LABELS,
        "INCIDENT_SEVERITY_COLORS": INCIDENT_SEVERITY_COLORS,
        "VALID_INCIDENT_CATEGORIES": VALID_INCIDENT_CATEGORIES,
        "INCIDENT_CATEGORY_LABELS": INCIDENT_CATEGORY_LABELS,
    })


# ==================== CREATE ====================

@router.get("/incidents/new", response_class=HTMLResponse)
async def incident_new_form(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    users = db.query(User).filter(User.is_active == True).order_by(User.display_name).all()
    vendors = db.query(Vendor).filter(Vendor.status == "ACTIVE").order_by(Vendor.name).all()
    return templates.TemplateResponse("incident_form.html", {
        "request": request,
        "incident": None,
        "users": users,
        "vendors": vendors,
        "VALID_INCIDENT_CATEGORIES": VALID_INCIDENT_CATEGORIES,
        "INCIDENT_CATEGORY_LABELS": INCIDENT_CATEGORY_LABELS,
        "VALID_INCIDENT_SEVERITIES": VALID_INCIDENT_SEVERITIES,
        "INCIDENT_SEVERITY_LABELS": INCIDENT_SEVERITY_LABELS,
    })


@router.post("/incidents/new", response_class=HTMLResponse)
async def incident_create(
    request: Request,
    title: str = Form(...),
    description: str = Form(None),
    category: str = Form(None),
    severity: str = Form("P3"),
    detection_method: str = Form(None),
    detected_at: str = Form(None),
    reported_at: str = Form(None),
    response_lead_user_id: int = Form(None),
    vendor_id: int = Form(None),
    affected_systems: str = Form(None),
    affected_users_count: int = Form(0),
    data_compromised: bool = Form(False),
    business_impact: str = Form(None),
    root_cause: str = Form(None),
    lessons_learned: str = Form(None),
    corrective_actions: str = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    detected_dt = datetime.strptime(detected_at, "%Y-%m-%d") if detected_at else None
    reported_dt = datetime.strptime(reported_at, "%Y-%m-%d") if reported_at else None

    incident = svc.create_incident(
        db,
        title=title, description=description,
        category=category, severity=severity,
        detection_method=detection_method,
        detected_at=detected_dt, reported_at=reported_dt,
        response_lead_user_id=response_lead_user_id,
        vendor_id=vendor_id,
        affected_systems=affected_systems,
        affected_users_count=affected_users_count,
        data_compromised=data_compromised,
        business_impact=business_impact,
        root_cause=root_cause,
        lessons_learned=lessons_learned,
        corrective_actions=corrective_actions,
        created_by_user_id=current_user.id,
    )
    log_audit(db, action=AUDIT_ACTION_CREATE, entity_type=AUDIT_ENTITY_INCIDENT,
              entity_id=incident.id, entity_label=incident.incident_ref,
              new_value={"title": title, "severity": severity}, actor_user=current_user)
    db.commit()
    return RedirectResponse(url=f"/incidents/{incident.id}", status_code=303)


# ==================== DETAIL ====================

@router.get("/incidents/{incident_id}", response_class=HTMLResponse)
async def incident_detail(
    request: Request,
    incident_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_login),
):
    incident = svc.get_incident(db, incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    all_controls = db.query(Control).filter(Control.is_active == True).order_by(Control.control_ref).all()
    all_risks = db.query(Risk).filter(Risk.is_active == True).order_by(Risk.risk_ref).all()
    return templates.TemplateResponse("incident_detail.html", {
        "request": request,
        "incident": incident,
        "all_controls": all_controls,
        "all_risks": all_risks,
        "VALID_INCIDENT_STATUSES": VALID_INCIDENT_STATUSES,
        "INCIDENT_STATUS_LABELS": INCIDENT_STATUS_LABELS,
        "INCIDENT_STATUS_COLORS": INCIDENT_STATUS_COLORS,
        "VALID_INCIDENT_SEVERITIES": VALID_INCIDENT_SEVERITIES,
        "INCIDENT_SEVERITY_LABELS": INCIDENT_SEVERITY_LABELS,
        "INCIDENT_SEVERITY_COLORS": INCIDENT_SEVERITY_COLORS,
        "VALID_INCIDENT_CATEGORIES": VALID_INCIDENT_CATEGORIES,
        "INCIDENT_CATEGORY_LABELS": INCIDENT_CATEGORY_LABELS,
    })


# ==================== EDIT ====================

@router.get("/incidents/{incident_id}/edit", response_class=HTMLResponse)
async def incident_edit_form(
    request: Request,
    incident_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    incident = svc.get_incident(db, incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    users = db.query(User).filter(User.is_active == True).order_by(User.display_name).all()
    vendors = db.query(Vendor).filter(Vendor.status == "ACTIVE").order_by(Vendor.name).all()
    return templates.TemplateResponse("incident_form.html", {
        "request": request,
        "incident": incident,
        "users": users,
        "vendors": vendors,
        "VALID_INCIDENT_CATEGORIES": VALID_INCIDENT_CATEGORIES,
        "INCIDENT_CATEGORY_LABELS": INCIDENT_CATEGORY_LABELS,
        "VALID_INCIDENT_SEVERITIES": VALID_INCIDENT_SEVERITIES,
        "INCIDENT_SEVERITY_LABELS": INCIDENT_SEVERITY_LABELS,
    })


@router.post("/incidents/{incident_id}/edit", response_class=HTMLResponse)
async def incident_edit(
    request: Request,
    incident_id: int,
    title: str = Form(...),
    description: str = Form(None),
    category: str = Form(None),
    severity: str = Form("P3"),
    detection_method: str = Form(None),
    detected_at: str = Form(None),
    reported_at: str = Form(None),
    response_lead_user_id: int = Form(None),
    vendor_id: int = Form(None),
    affected_systems: str = Form(None),
    affected_users_count: int = Form(0),
    data_compromised: bool = Form(False),
    business_impact: str = Form(None),
    root_cause: str = Form(None),
    lessons_learned: str = Form(None),
    corrective_actions: str = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    detected_dt = datetime.strptime(detected_at, "%Y-%m-%d") if detected_at else None
    reported_dt = datetime.strptime(reported_at, "%Y-%m-%d") if reported_at else None

    incident = svc.update_incident(
        db, incident_id,
        title=title, description=description,
        category=category, severity=severity,
        detection_method=detection_method,
        detected_at=detected_dt, reported_at=reported_dt,
        response_lead_user_id=response_lead_user_id,
        vendor_id=vendor_id,
        affected_systems=affected_systems,
        affected_users_count=affected_users_count,
        data_compromised=data_compromised,
        business_impact=business_impact,
        root_cause=root_cause,
        lessons_learned=lessons_learned,
        corrective_actions=corrective_actions,
    )
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    log_audit(db, action=AUDIT_ACTION_UPDATE, entity_type=AUDIT_ENTITY_INCIDENT,
              entity_id=incident.id, entity_label=incident.incident_ref,
              new_value={"title": title}, actor_user=current_user)
    db.commit()
    return RedirectResponse(url=f"/incidents/{incident_id}", status_code=303)


# ==================== DELETE ====================

@router.post("/incidents/{incident_id}/delete", response_class=HTMLResponse)
async def incident_delete(
    request: Request,
    incident_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_admin_dep),
):
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if incident:
        log_audit(db, action=AUDIT_ACTION_DELETE, entity_type=AUDIT_ENTITY_INCIDENT,
                  entity_id=incident.id, entity_label=incident.incident_ref,
                  actor_user=current_user)
        svc.delete_incident(db, incident_id)
        db.commit()
    return RedirectResponse(url="/incidents", status_code=303)


# ==================== STATUS UPDATE ====================

@router.post("/incidents/{incident_id}/status", response_class=HTMLResponse)
async def incident_status_update(
    request: Request,
    incident_id: int,
    status: str = Form(...),
    notes: str = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    incident, error = svc.update_status(db, incident_id, status,
                                         user_id=current_user.id, notes=notes)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    if error:
        # Redirect back with error message
        return RedirectResponse(
            url=f"/incidents/{incident_id}?message={error}&message_type=danger",
            status_code=303,
        )
    log_audit(db, action=AUDIT_ACTION_STATUS_CHANGE, entity_type=AUDIT_ENTITY_INCIDENT,
              entity_id=incident.id, entity_label=incident.incident_ref,
              new_value={"status": status}, actor_user=current_user)
    db.commit()
    return RedirectResponse(url=f"/incidents/{incident_id}", status_code=303)


# ==================== TIMELINE ====================

@router.post("/incidents/{incident_id}/timeline", response_class=HTMLResponse)
async def incident_add_timeline(
    request: Request,
    incident_id: int,
    event_type: str = Form(...),
    description: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    svc.add_timeline_entry(db, incident_id, event_type, description, user_id=current_user.id)
    log_audit(db, action=AUDIT_ACTION_UPDATE, entity_type=AUDIT_ENTITY_INCIDENT,
              entity_id=incident_id, entity_label=incident.incident_ref,
              description=f"Timeline entry added: {event_type}",
              actor_user=current_user)
    db.commit()
    return RedirectResponse(url=f"/incidents/{incident_id}#timeline", status_code=303)


# ==================== MAPPINGS ====================

@router.post("/incidents/{incident_id}/mappings/controls", response_class=HTMLResponse)
async def incident_save_control_mappings(
    request: Request,
    incident_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    form = await request.form()
    control_ids = [int(x) for x in form.getlist("control_ids") if x]
    relationship_type = form.get("relationship_type", "FAILED")
    svc.set_control_mappings(db, incident_id, control_ids, relationship_type)
    log_audit(db, action=AUDIT_ACTION_UPDATE, entity_type=AUDIT_ENTITY_INCIDENT,
              entity_id=incident_id, description="Updated control mappings",
              actor_user=current_user)
    db.commit()
    return RedirectResponse(url=f"/incidents/{incident_id}", status_code=303)


@router.post("/incidents/{incident_id}/mappings/risks", response_class=HTMLResponse)
async def incident_save_risk_mappings(
    request: Request,
    incident_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    form = await request.form()
    risk_ids = [int(x) for x in form.getlist("risk_ids") if x]
    svc.set_risk_mappings(db, incident_id, risk_ids)
    log_audit(db, action=AUDIT_ACTION_UPDATE, entity_type=AUDIT_ENTITY_INCIDENT,
              entity_id=incident_id, description="Updated risk mappings",
              actor_user=current_user)
    db.commit()
    return RedirectResponse(url=f"/incidents/{incident_id}", status_code=303)
