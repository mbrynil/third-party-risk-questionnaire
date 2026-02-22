"""Trust Center service — config management, public data assembly."""

import secrets
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func

from models import (
    TrustCenterConfig, FrameworkAdoption, FrameworkRequirement,
    Control, ControlImplementation, Policy, CustomFramework,
    ADOPTION_STATUS_MAPPED, ADOPTION_STATUS_NOT_APPLICABLE,
    IMPL_STATUS_IMPLEMENTED,
    POLICY_STATUS_APPROVED,
    AVAILABLE_FRAMEWORKS,
)


# ==================== CONFIG ====================

def get_config(db: Session) -> TrustCenterConfig:
    """Return the singleton TrustCenterConfig row."""
    return db.query(TrustCenterConfig).first()


def update_config(db: Session, **kwargs) -> TrustCenterConfig:
    """Update config fields on the singleton row."""
    config = get_config(db)
    if not config:
        return None
    for key, value in kwargs.items():
        if hasattr(config, key):
            setattr(config, key, value)
    config.updated_at = datetime.utcnow()
    db.flush()
    return config


def regenerate_token(db: Session) -> TrustCenterConfig:
    """Generate a new access token (invalidates old links)."""
    config = get_config(db)
    if not config:
        return None
    config.access_token = secrets.token_urlsafe(32)
    config.updated_at = datetime.utcnow()
    db.flush()
    return config


# ==================== PUBLIC DATA ====================

def get_public_data(db: Session) -> dict:
    """Build the data dictionary for the public trust center page."""
    config = get_config(db)
    if not config:
        return {}

    data = {
        "company_name": config.company_name,
        "company_description": config.company_description,
        "primary_color": config.primary_color or "#2563eb",
        "contact_email": config.contact_email,
        "custom_message": config.custom_message,
        "updated_at": config.updated_at,
    }

    # --- Frameworks ---
    if config.show_frameworks:
        data["frameworks"] = _build_framework_data(db)

    # --- Controls Summary ---
    if config.show_controls_summary:
        data["controls_summary"] = _build_controls_summary(db)

    # --- Policies ---
    if config.show_policies:
        data["policies"] = _build_policies_data(db)

    # --- Certifications ---
    if config.show_certifications:
        data["certifications"] = _build_certifications(db)

    return data


def _build_framework_data(db: Session) -> list:
    """Per-framework coverage: name, adopted count, total, percentage."""
    # Gather all framework keys (standard + custom)
    all_fw = {k: v for k, v in AVAILABLE_FRAMEWORKS}
    customs = db.query(CustomFramework).filter(CustomFramework.is_active == True).all()
    for c in customs:
        all_fw[c.framework_key] = c.display_name

    results = []
    for fw_key, fw_label in all_fw.items():
        total = db.query(FrameworkRequirement).filter(
            FrameworkRequirement.framework == fw_key,
            FrameworkRequirement.is_active == True,
        ).count()
        if total == 0:
            continue

        adoptions = db.query(FrameworkAdoption).filter(
            FrameworkAdoption.framework == fw_key,
        ).all()
        mapped = sum(1 for a in adoptions if a.status == ADOPTION_STATUS_MAPPED)
        na = sum(1 for a in adoptions if a.status == ADOPTION_STATUS_NOT_APPLICABLE)
        addressed = mapped + na
        pct = round(addressed / total * 100) if total > 0 else 0

        results.append({
            "key": fw_key,
            "name": fw_label,
            "total": total,
            "addressed": addressed,
            "coverage_pct": pct,
        })

    # Sort by coverage descending
    results.sort(key=lambda x: x["coverage_pct"], reverse=True)
    return results


def _build_controls_summary(db: Session) -> dict:
    """Total controls, implemented count, domain distribution."""
    total = db.query(Control).filter(Control.is_active == True).count()

    # Count org-level implementations that are IMPLEMENTED
    implemented = db.query(ControlImplementation).filter(
        ControlImplementation.vendor_id == None,
        ControlImplementation.status == IMPL_STATUS_IMPLEMENTED,
    ).count()

    implemented_pct = round(implemented / total * 100) if total > 0 else 0

    # Domain distribution
    domain_rows = (
        db.query(Control.domain, func.count(Control.id))
        .filter(Control.is_active == True)
        .group_by(Control.domain)
        .order_by(func.count(Control.id).desc())
        .all()
    )
    domains = [{"domain": row[0], "count": row[1]} for row in domain_rows]

    return {
        "total": total,
        "implemented": implemented,
        "implemented_pct": implemented_pct,
        "domains": domains,
    }


def _build_policies_data(db: Session) -> list:
    """Approved policies — title, domain, effective_date only (no content)."""
    policies = (
        db.query(Policy)
        .filter(Policy.status == POLICY_STATUS_APPROVED, Policy.is_active == True)
        .order_by(Policy.domain, Policy.title)
        .all()
    )
    return [
        {
            "title": p.title,
            "domain": p.domain or "General",
            "effective_date": p.effective_date,
        }
        for p in policies
    ]


def _build_certifications(db: Session) -> list:
    """Frameworks with >80% adoption rate listed as certifications."""
    fw_data = _build_framework_data(db)
    return [fw for fw in fw_data if fw["coverage_pct"] > 80]
