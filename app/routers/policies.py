"""Policy management module — library, workflow, mappings, acknowledgments, dashboard."""

from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from datetime import datetime

from app import templates
from models import (
    get_db, User, Control, Policy,
    VALID_POLICY_TYPES, POLICY_TYPE_LABELS,
    VALID_POLICY_STATUSES, POLICY_STATUS_LABELS, POLICY_STATUS_COLORS,
    POLICY_STATUS_DRAFT, POLICY_STATUS_UNDER_REVIEW, POLICY_STATUS_APPROVED,
    VALID_CONTROL_DOMAINS,
    AVAILABLE_FRAMEWORKS, FRAMEWORK_DISPLAY,
    AUDIT_ACTION_CREATE, AUDIT_ACTION_UPDATE, AUDIT_ACTION_DELETE, AUDIT_ACTION_STATUS_CHANGE,
    AUDIT_ENTITY_POLICY,
)
from app.services.auth_service import require_role, require_login
from app.services.audit_service import log_audit
from app.services import policy_service as svc
from app.services import policy_dashboard_service as dash_svc

router = APIRouter()
_analyst_dep = require_role("admin", "analyst")
_admin_dep = require_role("admin")


# ==================== POLICY LIBRARY ====================

@router.get("/policies", response_class=HTMLResponse)
async def policy_library(
    request: Request,
    status: str = None,
    domain: str = None,
    policy_type: str = None,
    owner_id: int = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "analyst")),
):
    policies = svc.get_all_policies(db, status=status, domain=domain, policy_type=policy_type, owner_id=owner_id)
    stats = svc.get_policy_stats(db)
    users = db.query(User).filter(User.is_active == True).order_by(User.display_name).all()
    kpis = {
        "total": stats["total"],
        "draft": stats["by_status"].get(POLICY_STATUS_DRAFT, 0),
        "under_review": stats["by_status"].get(POLICY_STATUS_UNDER_REVIEW, 0),
        "approved": stats["by_status"].get(POLICY_STATUS_APPROVED, 0),
    }
    return templates.TemplateResponse("policy_library.html", {
        "request": request,
        "policies": policies,
        "kpis": kpis,
        "users": users,
        "domains": VALID_CONTROL_DOMAINS,
        "policy_types": VALID_POLICY_TYPES,
        "f_status": status or "",
        "f_domain": domain or "",
        "f_type": policy_type or "",
        "f_owner": str(owner_id) if owner_id else "",
        "current_date": datetime.utcnow().date(),
        "VALID_POLICY_TYPES": VALID_POLICY_TYPES,
        "POLICY_TYPE_LABELS": POLICY_TYPE_LABELS,
        "VALID_POLICY_STATUSES": VALID_POLICY_STATUSES,
        "POLICY_STATUS_LABELS": POLICY_STATUS_LABELS,
        "POLICY_STATUS_COLORS": POLICY_STATUS_COLORS,
        "VALID_CONTROL_DOMAINS": VALID_CONTROL_DOMAINS,
    })


# ==================== POLICY DASHBOARD ====================

@router.get("/policies/dashboard", response_class=HTMLResponse)
async def policy_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_login),
):
    data = dash_svc.get_policy_dashboard_data(db)
    kpis = {
        "total": data["total"],
        "approved": data["by_status"].get(POLICY_STATUS_APPROVED, 0),
        "reviews_due": len(data["reviews_due"]),
        "ack_rate": data["ack_rate"],
    }
    # Domain coverage: for each domain with policies, compute total and approved count
    domain_coverage = []
    all_policies = db.query(Policy).filter(Policy.is_active == True).all()
    domain_map = {}
    for p in all_policies:
        d = p.domain or "Uncategorized"
        if d not in domain_map:
            domain_map[d] = {"total": 0, "approved": 0}
        domain_map[d]["total"] += 1
        if p.status == POLICY_STATUS_APPROVED:
            domain_map[d]["approved"] += 1
    for d, counts in sorted(domain_map.items()):
        pct = round(counts["approved"] / counts["total"] * 100) if counts["total"] > 0 else 0
        domain_coverage.append({"domain": d, "total": counts["total"], "approved": counts["approved"], "pct": pct})
    # Acknowledgment overview per approved policy
    from models import PolicyAcknowledgment
    ack_overview = []
    approved_policies = [p for p in all_policies if p.status == POLICY_STATUS_APPROVED]
    total_users = db.query(User).filter(User.is_active == True).count()
    for p in approved_policies:
        ack_count = db.query(PolicyAcknowledgment).filter(PolicyAcknowledgment.policy_id == p.id).count()
        pending = max(0, total_users - ack_count)
        rate = round(ack_count / total_users * 100) if total_users > 0 else 0
        ack_overview.append({"id": p.id, "policy_ref": p.policy_ref, "title": p.title, "acknowledged": ack_count, "pending": pending, "rate": rate})
    return templates.TemplateResponse("policy_dashboard.html", {
        "request": request,
        "kpis": kpis,
        "status_counts": data["by_status"],
        "domain_coverage": domain_coverage,
        "reviews_due": data["reviews_due"],
        "ack_overview": ack_overview,
        "current_date": datetime.utcnow().date(),
        "POLICY_STATUS_LABELS": POLICY_STATUS_LABELS,
        "POLICY_STATUS_COLORS": POLICY_STATUS_COLORS,
    })


# ==================== REVIEWS DUE ====================

@router.get("/policies/reviews", response_class=HTMLResponse)
async def policy_reviews(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "analyst")),
):
    policies = svc.get_policies_needing_review(db, days_ahead=90)
    return templates.TemplateResponse("policy_reviews.html", {
        "request": request,
        "policies": policies,
        "now": datetime.utcnow(),
    })


# ==================== ACKNOWLEDGMENTS ====================

@router.get("/policies/acknowledgments", response_class=HTMLResponse)
async def policy_acknowledgments(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_login),
):
    approved = svc.get_all_policies(db, status=POLICY_STATUS_APPROVED)
    from models import PolicyAcknowledgment
    my_acks = db.query(PolicyAcknowledgment).filter(
        PolicyAcknowledgment.user_id == current_user.id
    ).all()
    ack_map = {a.policy_id: a for a in my_acks}
    items = []
    for p in approved:
        ack = ack_map.get(p.id)
        items.append({
            "policy": p,
            "acknowledged": ack is not None,
            "acknowledged_at": ack.acknowledged_at if ack else None,
            "needs_reack": ack and ack.version_acknowledged and ack.version_acknowledged < (p.version or 1),
        })
    return templates.TemplateResponse("policy_acknowledgments.html", {
        "request": request,
        "items": items,
    })


# ==================== CREATE ====================

@router.get("/policies/new", response_class=HTMLResponse)
async def policy_new_form(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    users = db.query(User).filter(User.is_active == True).order_by(User.display_name).all()
    return templates.TemplateResponse("policy_form.html", {
        "request": request,
        "policy": None,
        "users": users,
        "VALID_POLICY_TYPES": VALID_POLICY_TYPES,
        "POLICY_TYPE_LABELS": POLICY_TYPE_LABELS,
        "VALID_CONTROL_DOMAINS": VALID_CONTROL_DOMAINS,
    })


@router.post("/policies/new", response_class=HTMLResponse)
async def policy_create(
    request: Request,
    title: str = Form(...),
    description: str = Form(None),
    content: str = Form(None),
    policy_type: str = Form("POLICY"),
    domain: str = Form(None),
    category: str = Form(None),
    owner_user_id: int = Form(None),
    review_frequency_days: int = Form(365),
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    policy = svc.create_policy(
        db, title=title, description=description, content=content,
        policy_type=policy_type, domain=domain, category=category,
        owner_user_id=owner_user_id, review_frequency_days=review_frequency_days,
    )
    log_audit(db, action=AUDIT_ACTION_CREATE, entity_type=AUDIT_ENTITY_POLICY,
              entity_id=policy.id, entity_label=policy.policy_ref,
              new_value={"title": title}, actor_user=current_user)
    db.commit()
    return RedirectResponse(url=f"/policies/{policy.id}", status_code=303)


# ==================== DETAIL ====================

@router.get("/policies/{policy_id}", response_class=HTMLResponse)
async def policy_detail(
    request: Request,
    policy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_login),
):
    policy = svc.get_policy(db, policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    all_controls = db.query(Control).filter(Control.is_active == True).order_by(Control.control_ref).all()
    ack_status = svc.get_acknowledgment_status(db, policy_id)
    # Check if current user has acknowledged
    from models import PolicyAcknowledgment
    my_ack = db.query(PolicyAcknowledgment).filter(
        PolicyAcknowledgment.policy_id == policy_id,
        PolicyAcknowledgment.user_id == current_user.id,
    ).first()
    return templates.TemplateResponse("policy_detail.html", {
        "request": request,
        "policy": policy,
        "all_controls": all_controls,
        "ack_status": ack_status,
        "my_ack": my_ack,
        "POLICY_STATUS_LABELS": POLICY_STATUS_LABELS,
        "POLICY_STATUS_COLORS": POLICY_STATUS_COLORS,
        "POLICY_TYPE_LABELS": POLICY_TYPE_LABELS,
        "AVAILABLE_FRAMEWORKS": AVAILABLE_FRAMEWORKS,
        "FRAMEWORK_DISPLAY": FRAMEWORK_DISPLAY,
    })


# ==================== EDIT ====================

@router.get("/policies/{policy_id}/edit", response_class=HTMLResponse)
async def policy_edit_form(
    request: Request,
    policy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    policy = svc.get_policy(db, policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    users = db.query(User).filter(User.is_active == True).order_by(User.display_name).all()
    return templates.TemplateResponse("policy_form.html", {
        "request": request,
        "policy": policy,
        "users": users,
        "VALID_POLICY_TYPES": VALID_POLICY_TYPES,
        "POLICY_TYPE_LABELS": POLICY_TYPE_LABELS,
        "VALID_CONTROL_DOMAINS": VALID_CONTROL_DOMAINS,
    })


@router.post("/policies/{policy_id}/edit", response_class=HTMLResponse)
async def policy_edit(
    request: Request,
    policy_id: int,
    title: str = Form(...),
    description: str = Form(None),
    content: str = Form(None),
    policy_type: str = Form("POLICY"),
    domain: str = Form(None),
    category: str = Form(None),
    owner_user_id: int = Form(None),
    review_frequency_days: int = Form(365),
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    policy = svc.update_policy(
        db, policy_id, title=title, description=description, content=content,
        policy_type=policy_type, domain=domain, category=category,
        owner_user_id=owner_user_id, review_frequency_days=review_frequency_days,
        editor_user_id=current_user.id,
    )
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    log_audit(db, action=AUDIT_ACTION_UPDATE, entity_type=AUDIT_ENTITY_POLICY,
              entity_id=policy.id, entity_label=policy.policy_ref,
              new_value={"title": title}, actor_user=current_user)
    db.commit()
    return RedirectResponse(url=f"/policies/{policy_id}", status_code=303)


# ==================== DELETE ====================

@router.post("/policies/{policy_id}/delete", response_class=HTMLResponse)
async def policy_delete(
    request: Request,
    policy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_admin_dep),
):
    policy = db.query(Policy).filter(Policy.id == policy_id).first()
    if policy:
        log_audit(db, action=AUDIT_ACTION_DELETE, entity_type=AUDIT_ENTITY_POLICY,
                  entity_id=policy.id, entity_label=policy.policy_ref,
                  actor_user=current_user)
        svc.delete_policy(db, policy_id)
        db.commit()
    return RedirectResponse(url="/policies", status_code=303)


# ==================== WORKFLOW ====================

@router.post("/policies/{policy_id}/submit-review", response_class=HTMLResponse)
async def policy_submit_review(
    request: Request, policy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    policy = svc.submit_for_review(db, policy_id)
    if policy:
        log_audit(db, action=AUDIT_ACTION_STATUS_CHANGE, entity_type=AUDIT_ENTITY_POLICY,
                  entity_id=policy.id, entity_label=policy.policy_ref,
                  new_value={"status": "UNDER_REVIEW"}, actor_user=current_user)
        db.commit()
    return RedirectResponse(url=f"/policies/{policy_id}", status_code=303)


@router.post("/policies/{policy_id}/approve", response_class=HTMLResponse)
async def policy_approve(
    request: Request, policy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_admin_dep),
):
    policy = svc.approve_policy(db, policy_id, current_user.id)
    if policy:
        log_audit(db, action=AUDIT_ACTION_STATUS_CHANGE, entity_type=AUDIT_ENTITY_POLICY,
                  entity_id=policy.id, entity_label=policy.policy_ref,
                  new_value={"status": "APPROVED"}, actor_user=current_user)
        db.commit()
    return RedirectResponse(url=f"/policies/{policy_id}", status_code=303)


@router.post("/policies/{policy_id}/retire", response_class=HTMLResponse)
async def policy_retire(
    request: Request, policy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_admin_dep),
):
    policy = svc.retire_policy(db, policy_id)
    if policy:
        log_audit(db, action=AUDIT_ACTION_STATUS_CHANGE, entity_type=AUDIT_ENTITY_POLICY,
                  entity_id=policy.id, entity_label=policy.policy_ref,
                  new_value={"status": "RETIRED"}, actor_user=current_user)
        db.commit()
    return RedirectResponse(url=f"/policies/{policy_id}", status_code=303)


@router.post("/policies/{policy_id}/revert-draft", response_class=HTMLResponse)
async def policy_revert_draft(
    request: Request, policy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    policy = svc.revert_to_draft(db, policy_id)
    if policy:
        log_audit(db, action=AUDIT_ACTION_STATUS_CHANGE, entity_type=AUDIT_ENTITY_POLICY,
                  entity_id=policy.id, entity_label=policy.policy_ref,
                  new_value={"status": "DRAFT"}, actor_user=current_user)
        db.commit()
    return RedirectResponse(url=f"/policies/{policy_id}", status_code=303)


# ==================== ACKNOWLEDGE ====================

@router.post("/policies/{policy_id}/acknowledge", response_class=HTMLResponse)
async def policy_acknowledge(
    request: Request, policy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_login),
):
    svc.acknowledge_policy(db, policy_id, current_user.id)
    db.commit()
    return RedirectResponse(url=f"/policies/{policy_id}", status_code=303)


# ==================== MAPPINGS ====================

@router.post("/policies/{policy_id}/mappings/controls", response_class=HTMLResponse)
async def policy_save_control_mappings(
    request: Request, policy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    form = await request.form()
    control_ids = [int(x) for x in form.getlist("control_ids") if x]
    svc.set_control_mappings(db, policy_id, control_ids)
    log_audit(db, action=AUDIT_ACTION_UPDATE, entity_type=AUDIT_ENTITY_POLICY,
              entity_id=policy_id, description="Updated control mappings",
              actor_user=current_user)
    db.commit()
    return RedirectResponse(url=f"/policies/{policy_id}", status_code=303)


@router.post("/policies/{policy_id}/mappings/frameworks", response_class=HTMLResponse)
async def policy_save_framework_mappings(
    request: Request, policy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    form = await request.form()
    frameworks = form.getlist("framework")
    references = form.getlist("requirement_reference")
    mappings = list(zip(frameworks, references))
    svc.set_framework_mappings(db, policy_id, mappings)
    log_audit(db, action=AUDIT_ACTION_UPDATE, entity_type=AUDIT_ENTITY_POLICY,
              entity_id=policy_id, description="Updated framework mappings",
              actor_user=current_user)
    db.commit()
    return RedirectResponse(url=f"/policies/{policy_id}", status_code=303)


# ==================== VERSION HISTORY ====================

@router.get("/policies/{policy_id}/versions", response_class=HTMLResponse)
async def policy_versions(
    request: Request, policy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_login),
):
    policy = svc.get_policy(db, policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    versions = svc.get_version_history(db, policy_id)
    return templates.TemplateResponse("policy_detail.html", {
        "request": request,
        "policy": policy,
        "versions": versions,
        "show_versions": True,
        "all_controls": [],
        "ack_status": [],
        "my_ack": None,
        "POLICY_STATUS_LABELS": POLICY_STATUS_LABELS,
        "POLICY_STATUS_COLORS": POLICY_STATUS_COLORS,
        "POLICY_TYPE_LABELS": POLICY_TYPE_LABELS,
        "AVAILABLE_FRAMEWORKS": AVAILABLE_FRAMEWORKS,
        "FRAMEWORK_DISPLAY": FRAMEWORK_DISPLAY,
    })
