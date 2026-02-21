"""Risk register module — register, assessment, treatment, mappings, dashboard, heatmap."""

from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from datetime import datetime

from app import templates
from models import (
    get_db, User, Control, Policy, Risk,
    VALID_RISK_SOURCES, RISK_SOURCE_LABELS,
    VALID_RISK_STATUSES, RISK_STATUS_LABELS, RISK_STATUS_COLORS,
    VALID_TREATMENT_TYPES, TREATMENT_TYPE_LABELS,
    VALID_TREATMENT_STATUSES, TREATMENT_STATUS_LABELS,
    VALID_CONTROL_DOMAINS,
    get_risk_level_label, RISK_LEVEL_COLORS,
    AUDIT_ACTION_CREATE, AUDIT_ACTION_UPDATE, AUDIT_ACTION_DELETE, AUDIT_ACTION_STATUS_CHANGE,
    AUDIT_ENTITY_RISK,
)
from app.services.auth_service import require_role, require_login
from app.services.audit_service import log_audit
from app.services import risk_service as svc
from app.services import risk_dashboard_service as dash_svc

router = APIRouter()
_analyst_dep = require_role("admin", "analyst")
_admin_dep = require_role("admin")


# ==================== RISK REGISTER ====================

@router.get("/risks", response_class=HTMLResponse)
async def risk_register(
    request: Request,
    status: str = None,
    category: str = None,
    source: str = None,
    owner_id: int = None,
    risk_level: str = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "analyst")),
):
    risks = svc.get_all_risks(db, status=status, category=category, source=source,
                               owner_id=owner_id, risk_level=risk_level)
    users = db.query(User).filter(User.is_active == True).order_by(User.display_name).all()
    return templates.TemplateResponse("risk_register.html", {
        "request": request,
        "risks": risks,
        "users": users,
        "filters": {"status": status, "category": category, "source": source, "owner_id": owner_id, "risk_level": risk_level},
        "VALID_RISK_SOURCES": VALID_RISK_SOURCES,
        "RISK_SOURCE_LABELS": RISK_SOURCE_LABELS,
        "VALID_RISK_STATUSES": VALID_RISK_STATUSES,
        "RISK_STATUS_LABELS": RISK_STATUS_LABELS,
        "RISK_STATUS_COLORS": RISK_STATUS_COLORS,
        "VALID_CONTROL_DOMAINS": VALID_CONTROL_DOMAINS,
        "get_risk_level_label": get_risk_level_label,
        "RISK_LEVEL_COLORS": RISK_LEVEL_COLORS,
    })


# ==================== RISK DASHBOARD ====================

@router.get("/risks/dashboard", response_class=HTMLResponse)
async def risk_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_login),
):
    data = dash_svc.get_risk_dashboard_data(db)
    return templates.TemplateResponse("risk_dashboard.html", {
        "request": request,
        "data": data,
        "get_risk_level_label": get_risk_level_label,
        "RISK_LEVEL_COLORS": RISK_LEVEL_COLORS,
    })


# ==================== HEATMAP ====================

@router.get("/risks/heatmap", response_class=HTMLResponse)
async def risk_heatmap(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_login),
):
    heatmap = svc.get_heatmap_data(db)
    return templates.TemplateResponse("risk_heatmap.html", {
        "request": request,
        "heatmap": heatmap,
        "get_risk_level_label": get_risk_level_label,
        "RISK_LEVEL_COLORS": RISK_LEVEL_COLORS,
    })


# ==================== CREATE ====================

@router.get("/risks/new", response_class=HTMLResponse)
async def risk_new_form(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    users = db.query(User).filter(User.is_active == True).order_by(User.display_name).all()
    return templates.TemplateResponse("risk_form.html", {
        "request": request,
        "risk": None,
        "users": users,
        "VALID_RISK_SOURCES": VALID_RISK_SOURCES,
        "RISK_SOURCE_LABELS": RISK_SOURCE_LABELS,
        "VALID_CONTROL_DOMAINS": VALID_CONTROL_DOMAINS,
        "VALID_TREATMENT_TYPES": VALID_TREATMENT_TYPES,
        "TREATMENT_TYPE_LABELS": TREATMENT_TYPE_LABELS,
    })


@router.post("/risks/new", response_class=HTMLResponse)
async def risk_create(
    request: Request,
    title: str = Form(...),
    description: str = Form(None),
    risk_category: str = Form(None),
    risk_source: str = Form(None),
    owner_user_id: int = Form(None),
    inherent_likelihood: int = Form(None),
    inherent_impact: int = Form(None),
    risk_appetite_threshold: int = Form(10),
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    risk = svc.create_risk(
        db, title=title, description=description,
        risk_category=risk_category, risk_source=risk_source,
        owner_user_id=owner_user_id,
        inherent_likelihood=inherent_likelihood, inherent_impact=inherent_impact,
        risk_appetite_threshold=risk_appetite_threshold,
    )
    log_audit(db, action=AUDIT_ACTION_CREATE, entity_type=AUDIT_ENTITY_RISK,
              entity_id=risk.id, entity_label=risk.risk_ref,
              new_value={"title": title}, actor_user=current_user)
    db.commit()
    return RedirectResponse(url=f"/risks/{risk.id}", status_code=303)


# ==================== DETAIL ====================

@router.get("/risks/{risk_id}", response_class=HTMLResponse)
async def risk_detail(
    request: Request,
    risk_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_login),
):
    risk = svc.get_risk(db, risk_id)
    if not risk:
        raise HTTPException(status_code=404, detail="Risk not found")
    all_controls = db.query(Control).filter(Control.is_active == True).order_by(Control.control_ref).all()
    all_policies = db.query(Policy).filter(Policy.is_active == True).order_by(Policy.policy_ref).all()
    return templates.TemplateResponse("risk_detail.html", {
        "request": request,
        "risk": risk,
        "all_controls": all_controls,
        "all_policies": all_policies,
        "RISK_STATUS_LABELS": RISK_STATUS_LABELS,
        "RISK_STATUS_COLORS": RISK_STATUS_COLORS,
        "RISK_SOURCE_LABELS": RISK_SOURCE_LABELS,
        "TREATMENT_TYPE_LABELS": TREATMENT_TYPE_LABELS,
        "TREATMENT_STATUS_LABELS": TREATMENT_STATUS_LABELS,
        "VALID_TREATMENT_TYPES": VALID_TREATMENT_TYPES,
        "get_risk_level_label": get_risk_level_label,
        "RISK_LEVEL_COLORS": RISK_LEVEL_COLORS,
    })


# ==================== EDIT ====================

@router.get("/risks/{risk_id}/edit", response_class=HTMLResponse)
async def risk_edit_form(
    request: Request,
    risk_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    risk = svc.get_risk(db, risk_id)
    if not risk:
        raise HTTPException(status_code=404, detail="Risk not found")
    users = db.query(User).filter(User.is_active == True).order_by(User.display_name).all()
    return templates.TemplateResponse("risk_form.html", {
        "request": request,
        "risk": risk,
        "users": users,
        "VALID_RISK_SOURCES": VALID_RISK_SOURCES,
        "RISK_SOURCE_LABELS": RISK_SOURCE_LABELS,
        "VALID_CONTROL_DOMAINS": VALID_CONTROL_DOMAINS,
        "VALID_TREATMENT_TYPES": VALID_TREATMENT_TYPES,
        "TREATMENT_TYPE_LABELS": TREATMENT_TYPE_LABELS,
    })


@router.post("/risks/{risk_id}/edit", response_class=HTMLResponse)
async def risk_edit(
    request: Request,
    risk_id: int,
    title: str = Form(...),
    description: str = Form(None),
    risk_category: str = Form(None),
    risk_source: str = Form(None),
    owner_user_id: int = Form(None),
    inherent_likelihood: int = Form(None),
    inherent_impact: int = Form(None),
    risk_appetite_threshold: int = Form(10),
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    risk = svc.update_risk(
        db, risk_id, title=title, description=description,
        risk_category=risk_category, risk_source=risk_source,
        owner_user_id=owner_user_id,
        inherent_likelihood=inherent_likelihood, inherent_impact=inherent_impact,
        risk_appetite_threshold=risk_appetite_threshold,
    )
    if not risk:
        raise HTTPException(status_code=404, detail="Risk not found")
    log_audit(db, action=AUDIT_ACTION_UPDATE, entity_type=AUDIT_ENTITY_RISK,
              entity_id=risk.id, entity_label=risk.risk_ref,
              new_value={"title": title}, actor_user=current_user)
    db.commit()
    return RedirectResponse(url=f"/risks/{risk_id}", status_code=303)


# ==================== DELETE ====================

@router.post("/risks/{risk_id}/delete", response_class=HTMLResponse)
async def risk_delete(
    request: Request,
    risk_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_admin_dep),
):
    risk = db.query(Risk).filter(Risk.id == risk_id).first()
    if risk:
        log_audit(db, action=AUDIT_ACTION_DELETE, entity_type=AUDIT_ENTITY_RISK,
                  entity_id=risk.id, entity_label=risk.risk_ref,
                  actor_user=current_user)
        svc.delete_risk(db, risk_id)
        db.commit()
    return RedirectResponse(url="/risks", status_code=303)


# ==================== ASSESSMENT & TREATMENT ====================

@router.post("/risks/{risk_id}/assess", response_class=HTMLResponse)
async def risk_assess(
    request: Request, risk_id: int,
    inherent_likelihood: int = Form(...),
    inherent_impact: int = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    risk = svc.assess_risk(db, risk_id, inherent_likelihood, inherent_impact)
    if risk:
        log_audit(db, action=AUDIT_ACTION_STATUS_CHANGE, entity_type=AUDIT_ENTITY_RISK,
                  entity_id=risk.id, entity_label=risk.risk_ref,
                  new_value={"inherent_score": risk.inherent_risk_score}, actor_user=current_user)
        db.commit()
    return RedirectResponse(url=f"/risks/{risk_id}", status_code=303)


@router.post("/risks/{risk_id}/treat", response_class=HTMLResponse)
async def risk_treat(
    request: Request, risk_id: int,
    treatment_type: str = Form(...),
    treatment_plan: str = Form(None),
    treatment_due_date: str = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    due_date = datetime.strptime(treatment_due_date, "%Y-%m-%d") if treatment_due_date else None
    risk = svc.set_treatment(db, risk_id, treatment_type, treatment_plan, due_date)
    if risk:
        log_audit(db, action=AUDIT_ACTION_STATUS_CHANGE, entity_type=AUDIT_ENTITY_RISK,
                  entity_id=risk.id, entity_label=risk.risk_ref,
                  new_value={"treatment_type": treatment_type}, actor_user=current_user)
        db.commit()
    return RedirectResponse(url=f"/risks/{risk_id}", status_code=303)


@router.post("/risks/{risk_id}/accept", response_class=HTMLResponse)
async def risk_accept(
    request: Request, risk_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    risk = svc.accept_risk(db, risk_id)
    if risk:
        log_audit(db, action=AUDIT_ACTION_STATUS_CHANGE, entity_type=AUDIT_ENTITY_RISK,
                  entity_id=risk.id, entity_label=risk.risk_ref,
                  new_value={"status": "ACCEPTED"}, actor_user=current_user)
        db.commit()
    return RedirectResponse(url=f"/risks/{risk_id}", status_code=303)


@router.post("/risks/{risk_id}/close", response_class=HTMLResponse)
async def risk_close(
    request: Request, risk_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    risk = svc.close_risk(db, risk_id)
    if risk:
        log_audit(db, action=AUDIT_ACTION_STATUS_CHANGE, entity_type=AUDIT_ENTITY_RISK,
                  entity_id=risk.id, entity_label=risk.risk_ref,
                  new_value={"status": "CLOSED"}, actor_user=current_user)
        db.commit()
    return RedirectResponse(url=f"/risks/{risk_id}", status_code=303)


@router.post("/risks/{risk_id}/reassess", response_class=HTMLResponse)
async def risk_reassess(
    request: Request, risk_id: int,
    residual_likelihood: int = Form(...),
    residual_impact: int = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    risk = svc.reassess_risk(db, risk_id, residual_likelihood, residual_impact)
    if risk:
        svc.take_snapshot(db, risk_id)
        log_audit(db, action=AUDIT_ACTION_UPDATE, entity_type=AUDIT_ENTITY_RISK,
                  entity_id=risk.id, entity_label=risk.risk_ref,
                  new_value={"residual_score": risk.residual_risk_score}, actor_user=current_user)
        db.commit()
    return RedirectResponse(url=f"/risks/{risk_id}", status_code=303)


# ==================== MAPPINGS ====================

@router.post("/risks/{risk_id}/mappings/controls", response_class=HTMLResponse)
async def risk_save_control_mappings(
    request: Request, risk_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    form = await request.form()
    control_ids = [int(x) for x in form.getlist("control_ids") if x]
    svc.set_control_mappings(db, risk_id, control_ids)
    log_audit(db, action=AUDIT_ACTION_UPDATE, entity_type=AUDIT_ENTITY_RISK,
              entity_id=risk_id, description="Updated control mappings",
              actor_user=current_user)
    db.commit()
    return RedirectResponse(url=f"/risks/{risk_id}", status_code=303)


@router.post("/risks/{risk_id}/mappings/policies", response_class=HTMLResponse)
async def risk_save_policy_mappings(
    request: Request, risk_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    form = await request.form()
    policy_ids = [int(x) for x in form.getlist("policy_ids") if x]
    svc.set_policy_mappings(db, risk_id, policy_ids)
    log_audit(db, action=AUDIT_ACTION_UPDATE, entity_type=AUDIT_ENTITY_RISK,
              entity_id=risk_id, description="Updated policy mappings",
              actor_user=current_user)
    db.commit()
    return RedirectResponse(url=f"/risks/{risk_id}", status_code=303)
