"""Asset inventory service — CRUD, control mappings, stats, dashboard."""

from datetime import datetime, timedelta
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from models import (
    Asset, AssetControlMapping, Control, User, Vendor,
    VALID_ASSET_TYPES, VALID_ASSET_STATUSES,
    ASSET_STATUS_ACTIVE, ASSET_STATUS_COLORS, ASSET_STATUS_LABELS,
    ASSET_TYPE_LABELS, ASSET_TYPE_ICONS,
)


def generate_asset_ref(db: Session) -> str:
    """Auto-generate ASSET-### reference."""
    existing = db.query(Asset.asset_ref).all()
    max_num = 0
    for (ref,) in existing:
        try:
            num = int(ref.split("-")[-1])
            if num > max_num:
                max_num = num
        except (ValueError, IndexError):
            pass
    return f"ASSET-{max_num + 1:03d}"


def get_all_assets(db: Session, status=None, asset_type=None, owner_id=None, vendor_id=None, environment=None):
    q = db.query(Asset).filter(Asset.is_active == True)
    if status:
        q = q.filter(Asset.status == status)
    if asset_type:
        q = q.filter(Asset.asset_type == asset_type)
    if owner_id:
        q = q.filter(Asset.owner_user_id == owner_id)
    if vendor_id:
        q = q.filter(Asset.vendor_id == vendor_id)
    if environment:
        q = q.filter(Asset.environment == environment)
    return q.options(
        joinedload(Asset.owner),
        joinedload(Asset.vendor),
    ).order_by(Asset.asset_ref).all()


def get_asset(db: Session, asset_id: int):
    return db.query(Asset).options(
        joinedload(Asset.owner),
        joinedload(Asset.vendor),
        joinedload(Asset.control_mappings).joinedload(AssetControlMapping.control),
    ).filter(Asset.id == asset_id).first()


def create_asset(db: Session, **kwargs):
    asset_ref = generate_asset_ref(db)
    asset = Asset(
        asset_ref=asset_ref,
        name=kwargs.get("name", ""),
        description=kwargs.get("description"),
        asset_type=kwargs.get("asset_type", "OTHER"),
        status=kwargs.get("status", ASSET_STATUS_ACTIVE),
        data_classification=kwargs.get("data_classification"),
        business_criticality=kwargs.get("business_criticality"),
        environment=kwargs.get("environment"),
        owner_user_id=kwargs.get("owner_user_id"),
        department=kwargs.get("department"),
        location=kwargs.get("location"),
        hostname=kwargs.get("hostname"),
        ip_address=kwargs.get("ip_address"),
        operating_system=kwargs.get("operating_system"),
        version=kwargs.get("version"),
        vendor_id=kwargs.get("vendor_id"),
        provider=kwargs.get("provider"),
        acquired_date=kwargs.get("acquired_date"),
        end_of_life_date=kwargs.get("end_of_life_date"),
    )
    db.add(asset)
    db.flush()
    return asset


def update_asset(db: Session, asset_id: int, **kwargs):
    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        return None
    for k, v in kwargs.items():
        if hasattr(asset, k):
            setattr(asset, k, v)
    db.flush()
    return asset


def delete_asset(db: Session, asset_id: int):
    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        return False
    asset.is_active = False
    db.flush()
    return True


def set_control_mappings(db: Session, asset_id: int, control_ids: list):
    db.query(AssetControlMapping).filter(AssetControlMapping.asset_id == asset_id).delete()
    for cid in control_ids:
        db.add(AssetControlMapping(asset_id=asset_id, control_id=cid))
    db.flush()


def get_asset_stats(db: Session) -> dict:
    """Return aggregate counts for assets."""
    base = db.query(Asset).filter(Asset.is_active == True)
    total = base.count()

    by_type = {}
    for t in VALID_ASSET_TYPES:
        by_type[t] = base.filter(Asset.asset_type == t).count()

    by_status = {}
    for s in VALID_ASSET_STATUSES:
        by_status[s] = base.filter(Asset.status == s).count()

    environments = ["Production", "Staging", "Development", "Test"]
    by_environment = {}
    for e in environments:
        by_environment[e] = base.filter(Asset.environment == e).count()

    criticalities = ["Critical", "High", "Medium", "Low"]
    by_criticality = {}
    for c in criticalities:
        by_criticality[c] = base.filter(Asset.business_criticality == c).count()

    return {
        "total": total,
        "by_type": by_type,
        "by_status": by_status,
        "by_environment": by_environment,
        "by_criticality": by_criticality,
    }


def get_asset_dashboard_data(db: Session) -> dict:
    """Return KPIs, distributions, and recent assets for the dashboard."""
    stats = get_asset_stats(db)
    base = db.query(Asset).filter(Asset.is_active == True)

    active_count = stats["by_status"].get("ACTIVE", 0)
    critical_count = stats["by_criticality"].get("Critical", 0) + stats["by_criticality"].get("High", 0)

    # EOL approaching: end_of_life_date within next 90 days
    now = datetime.utcnow()
    eol_cutoff = now + timedelta(days=90)
    eol_approaching = base.filter(
        Asset.end_of_life_date != None,
        Asset.end_of_life_date <= eol_cutoff,
        Asset.end_of_life_date >= now,
        Asset.status == ASSET_STATUS_ACTIVE,
    ).count()

    # Recent 10 assets
    recent_assets = base.options(
        joinedload(Asset.owner),
    ).order_by(Asset.created_at.desc()).limit(10).all()

    return {
        "total": stats["total"],
        "active": active_count,
        "critical": critical_count,
        "eol_approaching": eol_approaching,
        "by_type": stats["by_type"],
        "by_status": stats["by_status"],
        "by_environment": stats["by_environment"],
        "by_criticality": stats["by_criticality"],
        "recent_assets": recent_assets,
        "type_labels": ASSET_TYPE_LABELS,
        "type_icons": ASSET_TYPE_ICONS,
        "status_labels": ASSET_STATUS_LABELS,
        "status_colors": ASSET_STATUS_COLORS,
    }
