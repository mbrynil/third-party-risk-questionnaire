"""Audit readiness module — projects, PBC lists, evidence linking, binder export."""

import os
import uuid
from fastapi import APIRouter, Request, Form, Depends, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from sqlalchemy.orm import Session
from datetime import datetime

from app import templates
from models import (
    get_db, User, AuditProject, AuditRequest, AuditRequestEvidence,
    ControlEvidence, Policy, VendorDocument,
    AUDIT_PROJECT_STATUSES, AUDIT_PROJECT_STATUS_LABELS, AUDIT_PROJECT_STATUS_COLORS,
    AUDIT_REQUEST_STATUSES, AUDIT_REQUEST_STATUS_LABELS, AUDIT_REQUEST_STATUS_COLORS,
    AUDIT_REQUEST_PRIORITIES,
    AVAILABLE_FRAMEWORKS, FRAMEWORK_DISPLAY,
    AUDIT_ACTION_CREATE, AUDIT_ACTION_UPDATE, AUDIT_ACTION_DELETE,
    AUDIT_ENTITY_AUDIT_PROJECT,
)
from app.services.auth_service import require_role, require_login
from app.services.audit_service import log_audit
from app.services import audit_project_service as svc

router = APIRouter()
_analyst_dep = require_role("admin", "analyst")
_admin_dep = require_role("admin")


# ==================== PROJECT LIST ====================

@router.get("/audits", response_class=HTMLResponse)
async def audit_projects_list(
    request: Request,
    status: str = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "analyst")),
):
    projects = svc.get_all_audit_projects(db, status=status)
    return templates.TemplateResponse("audit_projects.html", {
        "request": request,
        "projects": projects,
        "filter_status": status,
        "AUDIT_PROJECT_STATUSES": AUDIT_PROJECT_STATUSES,
        "AUDIT_PROJECT_STATUS_LABELS": AUDIT_PROJECT_STATUS_LABELS,
        "AUDIT_PROJECT_STATUS_COLORS": AUDIT_PROJECT_STATUS_COLORS,
    })


# ==================== CREATE ====================

@router.get("/audits/new", response_class=HTMLResponse)
async def audit_project_new_form(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    users = db.query(User).filter(User.is_active == True).order_by(User.display_name).all()
    # Get dynamic frameworks
    from app.services import framework_service as fw_svc
    all_frameworks = fw_svc.get_all_frameworks_dynamic(db)
    return templates.TemplateResponse("audit_project_form.html", {
        "request": request,
        "project": None,
        "users": users,
        "ALL_FRAMEWORKS": all_frameworks,
        "AUDIT_PROJECT_STATUSES": AUDIT_PROJECT_STATUSES,
        "AUDIT_PROJECT_STATUS_LABELS": AUDIT_PROJECT_STATUS_LABELS,
    })


@router.post("/audits/new", response_class=HTMLResponse)
async def audit_project_create(
    request: Request,
    title: str = Form(...),
    framework: str = Form(...),
    scope_description: str = Form(None),
    auditor_name: str = Form(None),
    auditor_firm: str = Form(None),
    audit_period_start: str = Form(None),
    audit_period_end: str = Form(None),
    lead_user_id: int = Form(None),
    due_date: str = Form(None),
    notes: str = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    project = svc.create_audit_project(
        db,
        title=title, framework=framework,
        scope_description=scope_description,
        auditor_name=auditor_name, auditor_firm=auditor_firm,
        audit_period_start=datetime.strptime(audit_period_start, "%Y-%m-%d") if audit_period_start else None,
        audit_period_end=datetime.strptime(audit_period_end, "%Y-%m-%d") if audit_period_end else None,
        lead_user_id=lead_user_id,
        due_date=datetime.strptime(due_date, "%Y-%m-%d") if due_date else None,
        notes=notes,
    )
    log_audit(db, action=AUDIT_ACTION_CREATE, entity_type=AUDIT_ENTITY_AUDIT_PROJECT,
              entity_id=project.id, entity_label=project.title,
              new_value={"title": title, "framework": framework}, actor_user=current_user)
    db.commit()
    return RedirectResponse(url=f"/audits/{project.id}", status_code=303)


# ==================== DETAIL ====================

@router.get("/audits/{project_id}", response_class=HTMLResponse)
async def audit_project_detail(
    request: Request,
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "analyst")),
):
    project = svc.get_audit_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Audit project not found")
    stats = svc.get_request_stats(db, project_id)
    users = db.query(User).filter(User.is_active == True).order_by(User.display_name).all()
    fw_label = FRAMEWORK_DISPLAY.get(project.framework, project.framework)
    return templates.TemplateResponse("audit_project_detail.html", {
        "request": request,
        "project": project,
        "stats": stats,
        "users": users,
        "fw_label": fw_label,
        "AUDIT_PROJECT_STATUS_LABELS": AUDIT_PROJECT_STATUS_LABELS,
        "AUDIT_PROJECT_STATUS_COLORS": AUDIT_PROJECT_STATUS_COLORS,
        "AUDIT_REQUEST_STATUS_LABELS": AUDIT_REQUEST_STATUS_LABELS,
        "AUDIT_REQUEST_STATUS_COLORS": AUDIT_REQUEST_STATUS_COLORS,
        "AUDIT_REQUEST_STATUSES": AUDIT_REQUEST_STATUSES,
        "AUDIT_REQUEST_PRIORITIES": AUDIT_REQUEST_PRIORITIES,
    })


# ==================== EDIT ====================

@router.get("/audits/{project_id}/edit", response_class=HTMLResponse)
async def audit_project_edit_form(
    request: Request,
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    project = svc.get_audit_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Audit project not found")
    users = db.query(User).filter(User.is_active == True).order_by(User.display_name).all()
    from app.services import framework_service as fw_svc
    all_frameworks = fw_svc.get_all_frameworks_dynamic(db)
    return templates.TemplateResponse("audit_project_form.html", {
        "request": request,
        "project": project,
        "users": users,
        "ALL_FRAMEWORKS": all_frameworks,
        "AUDIT_PROJECT_STATUSES": AUDIT_PROJECT_STATUSES,
        "AUDIT_PROJECT_STATUS_LABELS": AUDIT_PROJECT_STATUS_LABELS,
    })


@router.post("/audits/{project_id}/edit", response_class=HTMLResponse)
async def audit_project_edit(
    request: Request,
    project_id: int,
    title: str = Form(...),
    framework: str = Form(...),
    scope_description: str = Form(None),
    auditor_name: str = Form(None),
    auditor_firm: str = Form(None),
    audit_period_start: str = Form(None),
    audit_period_end: str = Form(None),
    lead_user_id: int = Form(None),
    due_date: str = Form(None),
    notes: str = Form(None),
    status: str = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    project = svc.update_audit_project(
        db, project_id,
        title=title, framework=framework,
        scope_description=scope_description,
        auditor_name=auditor_name, auditor_firm=auditor_firm,
        audit_period_start=datetime.strptime(audit_period_start, "%Y-%m-%d") if audit_period_start else None,
        audit_period_end=datetime.strptime(audit_period_end, "%Y-%m-%d") if audit_period_end else None,
        lead_user_id=lead_user_id,
        due_date=datetime.strptime(due_date, "%Y-%m-%d") if due_date else None,
        notes=notes,
        status=status or "PLANNING",
    )
    if not project:
        raise HTTPException(status_code=404, detail="Audit project not found")
    log_audit(db, action=AUDIT_ACTION_UPDATE, entity_type=AUDIT_ENTITY_AUDIT_PROJECT,
              entity_id=project.id, entity_label=project.title,
              actor_user=current_user)
    db.commit()
    return RedirectResponse(url=f"/audits/{project_id}", status_code=303)


# ==================== DELETE ====================

@router.post("/audits/{project_id}/delete", response_class=HTMLResponse)
async def audit_project_delete(
    request: Request,
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_admin_dep),
):
    project = db.query(AuditProject).filter(AuditProject.id == project_id).first()
    if project:
        log_audit(db, action=AUDIT_ACTION_DELETE, entity_type=AUDIT_ENTITY_AUDIT_PROJECT,
                  entity_id=project.id, entity_label=project.title,
                  actor_user=current_user)
        svc.delete_audit_project(db, project_id)
        db.commit()
    return RedirectResponse(url="/audits", status_code=303)


# ==================== PBC GENERATION ====================

@router.post("/audits/{project_id}/generate-pbc", response_class=HTMLResponse)
async def audit_generate_pbc(
    request: Request, project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    result = svc.generate_pbc_list(db, project_id)
    db.commit()
    return RedirectResponse(url=f"/audits/{project_id}", status_code=303)


# ==================== AUTO-LINK ====================

@router.post("/audits/{project_id}/auto-link", response_class=HTMLResponse)
async def audit_auto_link(
    request: Request, project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    result = svc.auto_link_evidence(db, project_id)
    db.commit()
    return RedirectResponse(url=f"/audits/{project_id}", status_code=303)


# ==================== EXPORT BINDER ====================

@router.get("/audits/{project_id}/export", response_class=HTMLResponse)
async def audit_export_binder(
    request: Request, project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "analyst")),
):
    zip_path = svc.export_binder_zip(db, project_id)
    if not zip_path:
        raise HTTPException(status_code=404, detail="Audit project not found")
    project = db.query(AuditProject).filter(AuditProject.id == project_id).first()
    filename = f"audit_binder_{project.framework}_{project_id}.zip"
    return FileResponse(zip_path, media_type="application/zip", filename=filename)


# ==================== REQUEST DETAIL ====================

@router.get("/audits/{project_id}/requests/{request_id}", response_class=HTMLResponse)
async def audit_request_detail(
    request: Request,
    project_id: int,
    request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "analyst")),
):
    project = svc.get_audit_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Audit project not found")
    audit_req = db.query(AuditRequest).filter(AuditRequest.id == request_id).first()
    if not audit_req:
        raise HTTPException(status_code=404, detail="Request not found")
    users = db.query(User).filter(User.is_active == True).order_by(User.display_name).all()
    # Get available evidence for linking
    control_evidence = db.query(ControlEvidence).order_by(ControlEvidence.uploaded_at.desc()).limit(50).all()
    policies = db.query(Policy).filter(Policy.is_active == True).order_by(Policy.policy_ref).all()
    return templates.TemplateResponse("audit_request_detail.html", {
        "request": request,
        "project": project,
        "audit_req": audit_req,
        "users": users,
        "control_evidence": control_evidence,
        "policies": policies,
        "AUDIT_REQUEST_STATUS_LABELS": AUDIT_REQUEST_STATUS_LABELS,
        "AUDIT_REQUEST_STATUS_COLORS": AUDIT_REQUEST_STATUS_COLORS,
        "AUDIT_REQUEST_STATUSES": AUDIT_REQUEST_STATUSES,
    })


# ==================== REQUEST ACTIONS ====================

@router.post("/audits/{project_id}/requests/{request_id}/status", response_class=HTMLResponse)
async def audit_request_update_status(
    request: Request,
    project_id: int,
    request_id: int,
    status: str = Form(...),
    response_notes: str = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    svc.update_request_status(db, request_id, status, response_notes)
    db.commit()
    return RedirectResponse(url=f"/audits/{project_id}/requests/{request_id}", status_code=303)


@router.post("/audits/{project_id}/requests/{request_id}/assign", response_class=HTMLResponse)
async def audit_request_assign(
    request: Request,
    project_id: int,
    request_id: int,
    assigned_to_user_id: int = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    svc.assign_request(db, request_id, assigned_to_user_id)
    db.commit()
    return RedirectResponse(url=f"/audits/{project_id}/requests/{request_id}", status_code=303)


@router.post("/audits/{project_id}/requests/{request_id}/link-evidence", response_class=HTMLResponse)
async def audit_request_link_evidence(
    request: Request,
    project_id: int,
    request_id: int,
    evidence_type: str = Form(...),
    evidence_id: int = Form(None),
    notes: str = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    svc.link_evidence_to_request(db, request_id, evidence_type, evidence_id, notes=notes)
    db.commit()
    return RedirectResponse(url=f"/audits/{project_id}/requests/{request_id}", status_code=303)


@router.post("/audits/{project_id}/requests/{request_id}/upload", response_class=HTMLResponse)
async def audit_request_upload_evidence(
    request: Request,
    project_id: int,
    request_id: int,
    file: UploadFile = File(...),
    notes: str = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    # Save file
    upload_dir = os.path.join("uploads", "audit_evidence", str(project_id))
    os.makedirs(upload_dir, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}_{file.filename}"
    stored_path = os.path.join(upload_dir, stored_name)
    content = await file.read()
    with open(stored_path, "wb") as f:
        f.write(content)

    svc.link_evidence_to_request(
        db, request_id, "MANUAL_UPLOAD",
        manual_filename=file.filename, manual_stored_path=stored_path,
        notes=notes,
    )
    db.commit()
    return RedirectResponse(url=f"/audits/{project_id}/requests/{request_id}", status_code=303)


# ==================== ADD MANUAL REQUEST ====================

@router.post("/audits/{project_id}/requests/new", response_class=HTMLResponse)
async def audit_request_create(
    request: Request,
    project_id: int,
    request_title: str = Form(...),
    request_description: str = Form(None),
    priority: str = Form("MEDIUM"),
    due_date: str = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    audit_req = AuditRequest(
        audit_project_id=project_id,
        request_title=request_title,
        request_description=request_description,
        priority=priority,
        due_date=datetime.strptime(due_date, "%Y-%m-%d") if due_date else None,
    )
    db.add(audit_req)
    db.commit()
    return RedirectResponse(url=f"/audits/{project_id}", status_code=303)
