"""Framework requirement service — CRUD, adoption workflow, coverage stats, cross-mapping."""

from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func

from models import (
    FrameworkRequirement, FrameworkAdoption, Control, ControlFrameworkMapping,
    ControlImplementation,
    ADOPTION_STATUS_NOT_ADDRESSED, ADOPTION_STATUS_MAPPED, ADOPTION_STATUS_NOT_APPLICABLE,
    SEEDED_FRAMEWORKS, AVAILABLE_FRAMEWORKS, FRAMEWORK_DISPLAY,
    VALID_CONTROL_DOMAINS, IMPL_STATUS_IMPLEMENTED, IMPL_STATUS_NOT_IMPLEMENTED,
    CONTROL_TYPE_PREVENTIVE, CONTROL_IMPL_MANUAL, CONTROL_FREQ_ANNUAL,
)

# Domain → control ref prefix map for auto-generating CTL-XX-### refs
DOMAIN_REF_PREFIX = {
    "Access Control": "AC",
    "Asset Management": "AM",
    "Business Continuity": "BC",
    "Change Management": "CM",
    "Cryptography": "CR",
    "Data Protection": "DP",
    "Governance": "GV",
    "Human Resources": "HR",
    "Incident Management": "IR",
    "Network Security": "NS",
    "Physical Security": "PS",
    "Risk Management": "RM",
    "Secure Development": "SD",
    "Security Monitoring": "SM",
    "Security Operations": "SO",
    "Third-Party Management": "TP",
    "Training & Awareness": "TA",
    "Vulnerability Management": "VM",
}


# ==================== REQUIREMENT QUERIES ====================

def get_framework_requirements(db: Session, framework: str):
    return db.query(FrameworkRequirement).filter(
        FrameworkRequirement.framework == framework,
        FrameworkRequirement.is_active == True,
    ).order_by(FrameworkRequirement.sort_order, FrameworkRequirement.reference).all()


def get_requirements_grouped(db: Session, framework: str) -> dict:
    """Return requirements grouped by category > subcategory."""
    reqs = get_framework_requirements(db, framework)
    grouped = {}
    for r in reqs:
        cat = r.category or "Uncategorized"
        sub = r.subcategory or "General"
        grouped.setdefault(cat, {}).setdefault(sub, []).append(r)
    return grouped


def get_requirement_by_id(db: Session, req_id: int):
    return db.query(FrameworkRequirement).filter(FrameworkRequirement.id == req_id).first()


def get_requirement_count(db: Session, framework: str) -> int:
    return db.query(FrameworkRequirement).filter(
        FrameworkRequirement.framework == framework,
        FrameworkRequirement.is_active == True,
    ).count()


# ==================== FRAMEWORK STATS ====================

def get_framework_stats(db: Session) -> list:
    """Per-framework stats: total reqs, mapped, N/A, coverage %."""
    stats = []
    for fw_key in SEEDED_FRAMEWORKS:
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
        not_addressed = total - mapped - na

        # Count how many mapped controls are actually implemented (org-level)
        mapped_control_ids = [a.control_id for a in adoptions if a.status == ADOPTION_STATUS_MAPPED and a.control_id]
        implemented = 0
        if mapped_control_ids:
            implemented = db.query(ControlImplementation).filter(
                ControlImplementation.control_id.in_(mapped_control_ids),
                ControlImplementation.vendor_id == None,
                ControlImplementation.status == IMPL_STATUS_IMPLEMENTED,
            ).count()

        stats.append({
            "framework": fw_key,
            "label": FRAMEWORK_DISPLAY.get(fw_key, fw_key),
            "total": total,
            "mapped": mapped,
            "na": na,
            "not_addressed": not_addressed,
            "implemented": implemented,
            "mapped_pct": round(mapped / total * 100) if total > 0 else 0,
            "addressed_pct": round((mapped + na) / total * 100) if total > 0 else 0,
            "implemented_pct": round(implemented / total * 100) if total > 0 else 0,
        })
    return stats


def get_requirement_coverage(db: Session, framework: str) -> list:
    """Per-requirement detail: adoption status, mapped control, impl status."""
    reqs = get_framework_requirements(db, framework)
    if not reqs:
        return []

    # Build adoption lookup
    adoptions = db.query(FrameworkAdoption).filter(
        FrameworkAdoption.framework == framework,
    ).all()
    adoption_map = {a.requirement_reference: a for a in adoptions}

    # Build control lookup for mapped adoptions
    mapped_control_ids = [a.control_id for a in adoptions if a.control_id]
    controls = {}
    if mapped_control_ids:
        for c in db.query(Control).filter(Control.id.in_(mapped_control_ids)).all():
            controls[c.id] = c

    # Build impl lookup
    impl_map = {}
    if mapped_control_ids:
        impls = db.query(ControlImplementation).filter(
            ControlImplementation.control_id.in_(mapped_control_ids),
            ControlImplementation.vendor_id == None,
        ).all()
        impl_map = {i.control_id: i for i in impls}

    result = []
    for req in reqs:
        adoption = adoption_map.get(req.reference)
        control = controls.get(adoption.control_id) if adoption and adoption.control_id else None
        impl = impl_map.get(adoption.control_id) if adoption and adoption.control_id else None
        result.append({
            "requirement": req,
            "adoption": adoption,
            "status": adoption.status if adoption else ADOPTION_STATUS_NOT_ADDRESSED,
            "control": control,
            "implementation": impl,
            "impl_status": impl.status if impl else None,
        })
    return result


def get_category_coverage_stats(db: Session, framework: str) -> list:
    """Per-category coverage stats with percentage."""
    reqs = get_framework_requirements(db, framework)
    adoptions = db.query(FrameworkAdoption).filter(
        FrameworkAdoption.framework == framework,
    ).all()
    adoption_map = {a.requirement_reference: a for a in adoptions}

    cats = {}
    for req in reqs:
        cat = req.category or "Uncategorized"
        if cat not in cats:
            cats[cat] = {"total": 0, "mapped": 0, "na": 0}
        cats[cat]["total"] += 1
        a = adoption_map.get(req.reference)
        if a and a.status == ADOPTION_STATUS_MAPPED:
            cats[cat]["mapped"] += 1
        elif a and a.status == ADOPTION_STATUS_NOT_APPLICABLE:
            cats[cat]["na"] += 1

    result = []
    for cat, d in cats.items():
        addressed = d["mapped"] + d["na"]
        result.append({
            "category": cat,
            "total": d["total"],
            "mapped": d["mapped"],
            "na": d["na"],
            "not_addressed": d["total"] - addressed,
            "pct": round(addressed / d["total"] * 100) if d["total"] > 0 else 0,
        })
    return result


# ==================== ADMIN CRUD ====================

def update_requirement(db: Session, req_id: int, **kwargs):
    req = db.query(FrameworkRequirement).filter(FrameworkRequirement.id == req_id).first()
    if not req:
        return None
    for k, v in kwargs.items():
        if hasattr(req, k):
            setattr(req, k, v)
    db.flush()
    return req


# ==================== ADOPTION WORKFLOW ====================

def adopt_requirement_mapped(db: Session, framework: str, reference: str, control_id: int, user_id: int):
    """Link a requirement to an existing control."""
    adoption = db.query(FrameworkAdoption).filter(
        FrameworkAdoption.framework == framework,
        FrameworkAdoption.requirement_reference == reference,
    ).first()
    if adoption:
        adoption.status = ADOPTION_STATUS_MAPPED
        adoption.control_id = control_id
        adoption.adopted_by_user_id = user_id
        adoption.adopted_at = datetime.utcnow()
        adoption.notes = None
    else:
        adoption = FrameworkAdoption(
            framework=framework,
            requirement_reference=reference,
            status=ADOPTION_STATUS_MAPPED,
            control_id=control_id,
            adopted_by_user_id=user_id,
            adopted_at=datetime.utcnow(),
        )
        db.add(adoption)

    # Also ensure ControlFrameworkMapping exists
    existing_mapping = db.query(ControlFrameworkMapping).filter(
        ControlFrameworkMapping.control_id == control_id,
        ControlFrameworkMapping.framework == framework,
        ControlFrameworkMapping.reference == reference,
    ).first()
    if not existing_mapping:
        db.add(ControlFrameworkMapping(
            control_id=control_id,
            framework=framework,
            reference=reference,
        ))

    db.flush()
    return adoption


def adopt_requirement_as_na(db: Session, framework: str, reference: str, user_id: int, notes: str = ""):
    adoption = db.query(FrameworkAdoption).filter(
        FrameworkAdoption.framework == framework,
        FrameworkAdoption.requirement_reference == reference,
    ).first()
    if adoption:
        adoption.status = ADOPTION_STATUS_NOT_APPLICABLE
        adoption.control_id = None
        adoption.adopted_by_user_id = user_id
        adoption.adopted_at = datetime.utcnow()
        adoption.notes = notes
    else:
        adoption = FrameworkAdoption(
            framework=framework,
            requirement_reference=reference,
            status=ADOPTION_STATUS_NOT_APPLICABLE,
            adopted_by_user_id=user_id,
            adopted_at=datetime.utcnow(),
            notes=notes,
        )
        db.add(adoption)
    db.flush()
    return adoption


def unadopt_requirement(db: Session, framework: str, reference: str):
    """Reset a requirement back to NOT_ADDRESSED."""
    adoption = db.query(FrameworkAdoption).filter(
        FrameworkAdoption.framework == framework,
        FrameworkAdoption.requirement_reference == reference,
    ).first()
    if adoption:
        db.delete(adoption)
        db.flush()


def generate_next_control_ref(db: Session, domain: str) -> str:
    """Auto-generate next CTL-XX-### reference for a domain."""
    prefix = DOMAIN_REF_PREFIX.get(domain, "XX")
    pattern = f"CTL-{prefix}-%"
    existing = db.query(Control.control_ref).filter(
        Control.control_ref.like(pattern)
    ).all()
    max_num = 0
    for (ref,) in existing:
        try:
            num = int(ref.split("-")[-1])
            if num > max_num:
                max_num = num
        except (ValueError, IndexError):
            pass
    return f"CTL-{prefix}-{max_num + 1:03d}"


def auto_create_control_from_requirement(db: Session, req: FrameworkRequirement, user_id: int):
    """Create a new Control from a framework requirement and adopt it."""
    domain = req.suggested_domain or "Governance"
    if domain not in VALID_CONTROL_DOMAINS:
        domain = "Governance"
    control_ref = generate_next_control_ref(db, domain)

    ctrl = Control(
        control_ref=control_ref,
        title=req.title,
        description=req.description or "",
        domain=domain,
        control_type=req.suggested_control_type or CONTROL_TYPE_PREVENTIVE,
        implementation_type=CONTROL_IMPL_MANUAL,
        test_frequency=CONTROL_FREQ_ANNUAL,
        criticality="MEDIUM",
        is_active=True,
    )
    db.add(ctrl)
    db.flush()

    # Create framework mapping
    db.add(ControlFrameworkMapping(
        control_id=ctrl.id,
        framework=req.framework,
        reference=req.reference,
    ))

    # Create adoption record
    adopt_requirement_mapped(db, req.framework, req.reference, ctrl.id, user_id)

    return ctrl


def bulk_adopt_unmapped(db: Session, framework: str, user_id: int) -> dict:
    """Auto-create controls for all unmapped requirements in a framework."""
    reqs = get_framework_requirements(db, framework)
    adoptions = db.query(FrameworkAdoption).filter(
        FrameworkAdoption.framework == framework,
    ).all()
    addressed_refs = {a.requirement_reference for a in adoptions}

    created = 0
    skipped = 0
    for req in reqs:
        if req.reference in addressed_refs:
            skipped += 1
            continue
        auto_create_control_from_requirement(db, req, user_id)
        created += 1

    db.flush()
    return {"created": created, "skipped": skipped}


# ==================== CROSS-FRAMEWORK MAPPING ====================

def get_cross_framework_mappings(db: Session) -> list:
    """Controls mapped to 2+ frameworks for cross-reference view."""
    controls = db.query(Control).filter(Control.is_active == True).all()
    result = []
    for c in controls:
        if len(c.framework_mappings) < 2:
            continue
        fw_refs = {}
        for m in c.framework_mappings:
            fw_refs.setdefault(m.framework, []).append(m.reference)
        result.append({
            "control": c,
            "framework_refs": fw_refs,
        })
    return result


# ==================== CSV EXPORT ====================

def export_gap_analysis_csv(db: Session, framework: str) -> str:
    """Generate CSV content for gap analysis export."""
    coverage = get_requirement_coverage(db, framework)
    lines = ["Framework,Reference,Title,Category,Subcategory,Adoption Status,Mapped Control,Impl Status"]
    for item in coverage:
        req = item["requirement"]
        ctrl = item["control"]
        lines.append(",".join([
            _csv_escape(req.framework),
            _csv_escape(req.reference),
            _csv_escape(req.title),
            _csv_escape(req.category or ""),
            _csv_escape(req.subcategory or ""),
            _csv_escape(item["status"]),
            _csv_escape(ctrl.control_ref if ctrl else ""),
            _csv_escape(item["impl_status"] or ""),
        ]))
    return "\n".join(lines)


def _csv_escape(val: str) -> str:
    if not val:
        return ""
    val = str(val)
    if "," in val or '"' in val or "\n" in val:
        return '"' + val.replace('"', '""') + '"'
    return val
