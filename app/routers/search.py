"""Global search API."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_

from models import get_db, Vendor, Assessment, RemediationItem
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

    return {"results": results, "query": q}
