"""Asset inventory module — list, detail, create, edit, delete, control mappings, dashboard."""

from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from datetime import datetime

from app import templates
from models import (
    get_db, User, Vendor, Control, Asset, AssetControlMapping,
    VALID_ASSET_TYPES, ASSET_TYPE_LABELS, ASSET_TYPE_ICONS,
    VALID_ASSET_STATUSES, ASSET_STATUS_LABELS, ASSET_STATUS_COLORS,
    AUDIT_ACTION_CREATE, AUDIT_ACTION_UPDATE, AUDIT_ACTION_DELETE,
    AUDIT_ENTITY_ASSET,
)
from app.services.auth_service import require_role, require_login
from app.services.audit_service import log_audit
from app.services import asset_service as svc

router = APIRouter()
_analyst_dep = require_role("admin", "analyst")
_admin_dep = require_role("admin")


# ==================== ASSET LIST ====================

@router.get("/assets", response_class=HTMLResponse)
async def asset_list(
    request: Request,
    status: str = None,
    asset_type: str = None,
    owner_id: int = None,
    vendor_id: int = None,
    environment: str = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "analyst")),
):
    assets = svc.get_all_assets(db, status=status, asset_type=asset_type,
                                 owner_id=owner_id, vendor_id=vendor_id,
                                 environment=environment)
    users = db.query(User).filter(User.is_active == True).order_by(User.display_name).all()
    vendors = db.query(Vendor).order_by(Vendor.name).all()
    stats = svc.get_asset_stats(db)
    return templates.TemplateResponse("asset_list.html", {
        "request": request,
        "assets": assets,
        "users": users,
        "vendors": vendors,
        "stats": stats,
        "filters": {
            "status": status, "asset_type": asset_type,
            "owner_id": owner_id, "vendor_id": vendor_id,
            "environment": environment,
        },
        "VALID_ASSET_TYPES": VALID_ASSET_TYPES,
        "ASSET_TYPE_LABELS": ASSET_TYPE_LABELS,
        "ASSET_TYPE_ICONS": ASSET_TYPE_ICONS,
        "VALID_ASSET_STATUSES": VALID_ASSET_STATUSES,
        "ASSET_STATUS_LABELS": ASSET_STATUS_LABELS,
        "ASSET_STATUS_COLORS": ASSET_STATUS_COLORS,
    })


# ==================== ASSET DASHBOARD ====================

@router.get("/assets/dashboard", response_class=HTMLResponse)
async def asset_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_login),
):
    data = svc.get_asset_dashboard_data(db)
    return templates.TemplateResponse("asset_dashboard.html", {
        "request": request,
        "data": data,
        "ASSET_TYPE_LABELS": ASSET_TYPE_LABELS,
        "ASSET_TYPE_ICONS": ASSET_TYPE_ICONS,
        "ASSET_STATUS_LABELS": ASSET_STATUS_LABELS,
        "ASSET_STATUS_COLORS": ASSET_STATUS_COLORS,
    })


# ==================== CREATE ====================

@router.get("/assets/new", response_class=HTMLResponse)
async def asset_new_form(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    users = db.query(User).filter(User.is_active == True).order_by(User.display_name).all()
    vendors = db.query(Vendor).order_by(Vendor.name).all()
    return templates.TemplateResponse("asset_form.html", {
        "request": request,
        "asset": None,
        "users": users,
        "vendors": vendors,
        "VALID_ASSET_TYPES": VALID_ASSET_TYPES,
        "ASSET_TYPE_LABELS": ASSET_TYPE_LABELS,
        "VALID_ASSET_STATUSES": VALID_ASSET_STATUSES,
        "ASSET_STATUS_LABELS": ASSET_STATUS_LABELS,
    })


@router.post("/assets/new", response_class=HTMLResponse)
async def asset_create(
    request: Request,
    name: str = Form(...),
    description: str = Form(None),
    asset_type: str = Form("OTHER"),
    status: str = Form("ACTIVE"),
    data_classification: str = Form(None),
    business_criticality: str = Form(None),
    environment: str = Form(None),
    owner_user_id: int = Form(None),
    department: str = Form(None),
    location: str = Form(None),
    hostname: str = Form(None),
    ip_address: str = Form(None),
    operating_system: str = Form(None),
    version: str = Form(None),
    vendor_id: int = Form(None),
    provider: str = Form(None),
    acquired_date: str = Form(None),
    end_of_life_date: str = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    acq = datetime.strptime(acquired_date, "%Y-%m-%d") if acquired_date else None
    eol = datetime.strptime(end_of_life_date, "%Y-%m-%d") if end_of_life_date else None

    asset = svc.create_asset(
        db, name=name, description=description,
        asset_type=asset_type, status=status,
        data_classification=data_classification or None,
        business_criticality=business_criticality or None,
        environment=environment or None,
        owner_user_id=owner_user_id, department=department or None,
        location=location or None, hostname=hostname or None,
        ip_address=ip_address or None, operating_system=operating_system or None,
        version=version or None, vendor_id=vendor_id,
        provider=provider or None,
        acquired_date=acq, end_of_life_date=eol,
    )
    log_audit(db, action=AUDIT_ACTION_CREATE, entity_type=AUDIT_ENTITY_ASSET,
              entity_id=asset.id, entity_label=asset.asset_ref,
              new_value={"name": name, "type": asset_type}, actor_user=current_user)
    db.commit()
    return RedirectResponse(url=f"/assets/{asset.id}", status_code=303)


# ==================== DETAIL ====================

@router.get("/assets/{asset_id}", response_class=HTMLResponse)
async def asset_detail(
    request: Request,
    asset_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_login),
):
    asset = svc.get_asset(db, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    all_controls = db.query(Control).filter(Control.is_active == True).order_by(Control.control_ref).all()
    return templates.TemplateResponse("asset_detail.html", {
        "request": request,
        "asset": asset,
        "all_controls": all_controls,
        "ASSET_TYPE_LABELS": ASSET_TYPE_LABELS,
        "ASSET_TYPE_ICONS": ASSET_TYPE_ICONS,
        "ASSET_STATUS_LABELS": ASSET_STATUS_LABELS,
        "ASSET_STATUS_COLORS": ASSET_STATUS_COLORS,
    })


# ==================== EDIT ====================

@router.get("/assets/{asset_id}/edit", response_class=HTMLResponse)
async def asset_edit_form(
    request: Request,
    asset_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    asset = svc.get_asset(db, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    users = db.query(User).filter(User.is_active == True).order_by(User.display_name).all()
    vendors = db.query(Vendor).order_by(Vendor.name).all()
    return templates.TemplateResponse("asset_form.html", {
        "request": request,
        "asset": asset,
        "users": users,
        "vendors": vendors,
        "VALID_ASSET_TYPES": VALID_ASSET_TYPES,
        "ASSET_TYPE_LABELS": ASSET_TYPE_LABELS,
        "VALID_ASSET_STATUSES": VALID_ASSET_STATUSES,
        "ASSET_STATUS_LABELS": ASSET_STATUS_LABELS,
    })


@router.post("/assets/{asset_id}/edit", response_class=HTMLResponse)
async def asset_edit(
    request: Request,
    asset_id: int,
    name: str = Form(...),
    description: str = Form(None),
    asset_type: str = Form("OTHER"),
    status: str = Form("ACTIVE"),
    data_classification: str = Form(None),
    business_criticality: str = Form(None),
    environment: str = Form(None),
    owner_user_id: int = Form(None),
    department: str = Form(None),
    location: str = Form(None),
    hostname: str = Form(None),
    ip_address: str = Form(None),
    operating_system: str = Form(None),
    version: str = Form(None),
    vendor_id: int = Form(None),
    provider: str = Form(None),
    acquired_date: str = Form(None),
    end_of_life_date: str = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    acq = datetime.strptime(acquired_date, "%Y-%m-%d") if acquired_date else None
    eol = datetime.strptime(end_of_life_date, "%Y-%m-%d") if end_of_life_date else None

    asset = svc.update_asset(
        db, asset_id, name=name, description=description,
        asset_type=asset_type, status=status,
        data_classification=data_classification or None,
        business_criticality=business_criticality or None,
        environment=environment or None,
        owner_user_id=owner_user_id, department=department or None,
        location=location or None, hostname=hostname or None,
        ip_address=ip_address or None, operating_system=operating_system or None,
        version=version or None, vendor_id=vendor_id,
        provider=provider or None,
        acquired_date=acq, end_of_life_date=eol,
    )
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    log_audit(db, action=AUDIT_ACTION_UPDATE, entity_type=AUDIT_ENTITY_ASSET,
              entity_id=asset.id, entity_label=asset.asset_ref,
              new_value={"name": name}, actor_user=current_user)
    db.commit()
    return RedirectResponse(url=f"/assets/{asset_id}", status_code=303)


# ==================== DELETE ====================

@router.post("/assets/{asset_id}/delete", response_class=HTMLResponse)
async def asset_delete(
    request: Request,
    asset_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_admin_dep),
):
    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if asset:
        log_audit(db, action=AUDIT_ACTION_DELETE, entity_type=AUDIT_ENTITY_ASSET,
                  entity_id=asset.id, entity_label=asset.asset_ref,
                  actor_user=current_user)
        svc.delete_asset(db, asset_id)
        db.commit()
    return RedirectResponse(url="/assets", status_code=303)


# ==================== CONTROL MAPPINGS ====================

@router.post("/assets/{asset_id}/mappings/controls", response_class=HTMLResponse)
async def asset_save_control_mappings(
    request: Request,
    asset_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    form = await request.form()
    control_ids = [int(x) for x in form.getlist("control_ids") if x]
    svc.set_control_mappings(db, asset_id, control_ids)
    log_audit(db, action=AUDIT_ACTION_UPDATE, entity_type=AUDIT_ENTITY_ASSET,
              entity_id=asset_id, description="Updated control mappings",
              actor_user=current_user)
    db.commit()
    return RedirectResponse(url=f"/assets/{asset_id}", status_code=303)
