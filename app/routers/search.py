"""Global search API."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_

from models import get_db, Vendor, Assessment, RemediationItem, Control, Incident, Asset
from app.services.auth_service import require_login

router = APIRouter()


@router.get("/api/search")
def api_search(
    q: str = Query("", min_length=1),
    db: Session = Depends(get_db),
    user=Depends(require_login),
):
    """Search vendors, assessments, and remediations."""
    term = f"%{q.strip()}%"
    results = []

    # Vendors
    vendors = db.query(Vendor).filter(
        or_(Vendor.name.ilike(term), Vendor.industry.ilike(term),
            Vendor.primary_contact_name.ilike(term))
    ).limit(5).all()
    for v in vendors:
        results.append({
            "type": "vendor",
            "icon": "bi-building",
            "title": v.name,
            "subtitle": v.industry or v.service_type or "",
            "url": f"/vendors/{v.id}",
        })

    # Assessments
    assessments = db.query(Assessment).filter(
        or_(Assessment.title.ilike(term), Assessment.company_name.ilike(term))
    ).limit(5).all()
    for a in assessments:
        results.append({
            "type": "assessment",
            "icon": "bi-clipboard-check",
            "title": a.title,
            "subtitle": f"{a.company_name} — {a.status.replace('_', ' ').title()}",
            "url": f"/assessments/{a.id}/decision" if a.status in ("SUBMITTED", "REVIEWED") else f"/assessments/{a.id}/manage",
        })

    # Remediations
    remediations = db.query(RemediationItem).filter(
        RemediationItem.title.ilike(term)
    ).limit(5).all()
    for r in remediations:
        results.append({
            "type": "remediation",
            "icon": "bi-wrench",
            "title": r.title[:80],
            "subtitle": f"{r.status.replace('_', ' ').title()} — {r.severity}",
            "url": f"/remediations/{r.id}",
        })

    # Controls
    controls = db.query(Control).filter(
        or_(Control.title.ilike(term), Control.control_ref.ilike(term),
            Control.domain.ilike(term))
    ).limit(5).all()
    for c in controls:
        results.append({
            "type": "control",
            "icon": "bi-shield-lock",
            "title": f"{c.control_ref} — {c.title}",
            "subtitle": c.domain,
            "url": f"/controls/{c.id}",
        })

    # Incidents
    incidents = db.query(Incident).filter(
        or_(Incident.incident_ref.ilike(term), Incident.title.ilike(term))
    ).limit(5).all()
    for inc in incidents:
        results.append({
            "type": "incident",
            "icon": "bi-exclamation-diamond",
            "title": f"{inc.incident_ref} — {inc.title}",
            "subtitle": f"{inc.severity} — {inc.status.replace('_', ' ').title()}",
            "url": f"/incidents/{inc.id}",
        })

    # Assets
    assets = db.query(Asset).filter(
        or_(Asset.asset_ref.ilike(term), Asset.name.ilike(term))
    ).limit(5).all()
    for asset in assets:
        results.append({
            "type": "asset",
            "icon": "bi-hdd-rack",
            "title": f"{asset.asset_ref} — {asset.name}",
            "subtitle": f"{asset.asset_type} — {asset.status.replace('_', ' ').title()}",
            "url": f"/assets/{asset.id}",
        })

    return {"results": results, "query": q}
