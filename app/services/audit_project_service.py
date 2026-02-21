"""Audit readiness service — project CRUD, PBC generation, evidence linking, binder export."""

import os
import json
import zipfile
import tempfile
from datetime import datetime
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from models import (
    AuditProject, AuditRequest, AuditRequestEvidence,
    FrameworkRequirement, FrameworkAdoption, ControlEvidence,
    Policy, PolicyFrameworkMapping, VendorDocument,
    User, ADOPTION_STATUS_MAPPED,
)


def get_all_audit_projects(db: Session, status=None):
    q = db.query(AuditProject).options(joinedload(AuditProject.lead))
    if status:
        q = q.filter(AuditProject.status == status)
    return q.order_by(AuditProject.created_at.desc()).all()


def get_audit_project(db: Session, project_id: int):
    return db.query(AuditProject).options(
        joinedload(AuditProject.lead),
        joinedload(AuditProject.requests).joinedload(AuditRequest.assigned_to),
        joinedload(AuditProject.requests).joinedload(AuditRequest.evidence_links),
    ).filter(AuditProject.id == project_id).first()


def create_audit_project(db: Session, **kwargs):
    project = AuditProject(
        title=kwargs.get("title", ""),
        framework=kwargs.get("framework", ""),
        scope_description=kwargs.get("scope_description"),
        auditor_name=kwargs.get("auditor_name"),
        auditor_firm=kwargs.get("auditor_firm"),
        audit_period_start=kwargs.get("audit_period_start"),
        audit_period_end=kwargs.get("audit_period_end"),
        status=kwargs.get("status", "PLANNING"),
        lead_user_id=kwargs.get("lead_user_id"),
        due_date=kwargs.get("due_date"),
        notes=kwargs.get("notes"),
    )
    db.add(project)
    db.flush()
    return project


def update_audit_project(db: Session, project_id: int, **kwargs):
    project = db.query(AuditProject).filter(AuditProject.id == project_id).first()
    if not project:
        return None
    for k, v in kwargs.items():
        if hasattr(project, k):
            setattr(project, k, v)
    db.flush()
    return project


def delete_audit_project(db: Session, project_id: int):
    project = db.query(AuditProject).filter(AuditProject.id == project_id).first()
    if not project:
        return False
    db.delete(project)
    db.flush()
    return True


def generate_pbc_list(db: Session, project_id: int) -> dict:
    """Auto-create AuditRequest for each FrameworkRequirement that has a MAPPED adoption."""
    project = db.query(AuditProject).filter(AuditProject.id == project_id).first()
    if not project:
        return {"created": 0, "skipped": 0}

    # Get requirements for this framework
    reqs = db.query(FrameworkRequirement).filter(
        FrameworkRequirement.framework == project.framework,
        FrameworkRequirement.is_active == True,
    ).order_by(FrameworkRequirement.sort_order, FrameworkRequirement.reference).all()

    # Get existing request references to avoid duplicates
    existing_refs = set(
        r.requirement_reference for r in db.query(AuditRequest).filter(
            AuditRequest.audit_project_id == project_id
        ).all() if r.requirement_reference
    )

    created = 0
    skipped = 0
    for req in reqs:
        if req.reference in existing_refs:
            skipped += 1
            continue
        db.add(AuditRequest(
            audit_project_id=project_id,
            requirement_reference=req.reference,
            request_title=f"[{req.reference}] {req.title}",
            request_description=req.description or "",
            priority="MEDIUM",
            due_date=project.due_date,
        ))
        created += 1

    db.flush()
    return {"created": created, "skipped": skipped}


def auto_link_evidence(db: Session, project_id: int) -> dict:
    """Scan ControlEvidence with matching framework_tags + policies with matching framework mappings."""
    project = db.query(AuditProject).filter(AuditProject.id == project_id).first()
    if not project:
        return {"linked": 0}

    requests = db.query(AuditRequest).filter(
        AuditRequest.audit_project_id == project_id,
    ).all()

    linked = 0
    for req in requests:
        if not req.requirement_reference:
            continue

        # Check existing links
        existing_evidence_ids = set()
        existing_policy_ids = set()
        for el in req.evidence_links:
            if el.control_evidence_id:
                existing_evidence_ids.add(el.control_evidence_id)
            if el.policy_id:
                existing_policy_ids.add(el.policy_id)

        # Find control evidence with matching framework tags
        all_evidence = db.query(ControlEvidence).filter(
            ControlEvidence.framework_tags != None,
        ).all()
        for ev in all_evidence:
            if ev.id in existing_evidence_ids:
                continue
            try:
                tags = json.loads(ev.framework_tags) if ev.framework_tags else []
            except (json.JSONDecodeError, TypeError):
                tags = []
            if project.framework in tags:
                db.add(AuditRequestEvidence(
                    audit_request_id=req.id,
                    evidence_type="CONTROL_EVIDENCE",
                    control_evidence_id=ev.id,
                    notes="Auto-linked by framework tag match",
                ))
                linked += 1

        # Find policies with matching framework mappings
        policy_mappings = db.query(PolicyFrameworkMapping).filter(
            PolicyFrameworkMapping.framework == project.framework,
            PolicyFrameworkMapping.requirement_reference == req.requirement_reference,
        ).all()
        for pm in policy_mappings:
            if pm.policy_id in existing_policy_ids:
                continue
            db.add(AuditRequestEvidence(
                audit_request_id=req.id,
                evidence_type="POLICY",
                policy_id=pm.policy_id,
                notes="Auto-linked by policy-framework mapping",
            ))
            linked += 1

    db.flush()
    return {"linked": linked}


def get_request_stats(db: Session, project_id: int) -> dict:
    requests = db.query(AuditRequest).filter(
        AuditRequest.audit_project_id == project_id,
    ).all()
    total = len(requests)
    stats = {"total": total, "OPEN": 0, "IN_PROGRESS": 0, "PROVIDED": 0, "ACCEPTED": 0, "REJECTED": 0}
    for r in requests:
        if r.status in stats:
            stats[r.status] += 1

    # Evidence coverage
    with_evidence = sum(1 for r in requests if len(r.evidence_links) > 0)
    stats["with_evidence"] = with_evidence
    stats["coverage_pct"] = round(with_evidence / total * 100) if total > 0 else 0
    return stats


def get_evidence_coverage(db: Session, project_id: int) -> list:
    """Per-request evidence status."""
    requests = db.query(AuditRequest).options(
        joinedload(AuditRequest.evidence_links),
        joinedload(AuditRequest.assigned_to),
    ).filter(
        AuditRequest.audit_project_id == project_id,
    ).order_by(AuditRequest.requirement_reference).all()

    result = []
    for req in requests:
        result.append({
            "request": req,
            "evidence_count": len(req.evidence_links),
            "has_evidence": len(req.evidence_links) > 0,
        })
    return result


def link_evidence_to_request(db: Session, request_id: int, evidence_type: str, evidence_id: int = None,
                              manual_filename: str = None, manual_stored_path: str = None, notes: str = None):
    link = AuditRequestEvidence(
        audit_request_id=request_id,
        evidence_type=evidence_type,
        notes=notes,
    )
    if evidence_type == "CONTROL_EVIDENCE":
        link.control_evidence_id = evidence_id
    elif evidence_type == "POLICY":
        link.policy_id = evidence_id
    elif evidence_type == "VENDOR_DOCUMENT":
        link.vendor_document_id = evidence_id
    elif evidence_type == "MANUAL_UPLOAD":
        link.manual_filename = manual_filename
        link.manual_stored_path = manual_stored_path
    db.add(link)
    db.flush()
    return link


def update_request_status(db: Session, request_id: int, status: str, notes: str = None):
    req = db.query(AuditRequest).filter(AuditRequest.id == request_id).first()
    if not req:
        return None
    req.status = status
    if notes:
        req.response_notes = notes
    if status in ("ACCEPTED", "REJECTED"):
        req.completed_at = datetime.utcnow()
    db.flush()
    return req


def assign_request(db: Session, request_id: int, user_id: int):
    req = db.query(AuditRequest).filter(AuditRequest.id == request_id).first()
    if req:
        req.assigned_to_user_id = user_id
        db.flush()
    return req


def export_binder_zip(db: Session, project_id: int) -> str:
    """Generate ZIP organized by requirement reference with index.html cover page.
    Returns path to temporary ZIP file."""
    project = get_audit_project(db, project_id)
    if not project:
        return None

    tmp_dir = tempfile.mkdtemp()
    zip_path = os.path.join(tmp_dir, f"audit_binder_{project.id}.zip")

    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        # Build index data
        req_rows = []
        for req in sorted(project.requests, key=lambda r: r.requirement_reference or ""):
            evidence_items = []
            for el in req.evidence_links:
                if el.evidence_type == "CONTROL_EVIDENCE" and el.control_evidence:
                    evidence_items.append(f"Control Evidence: {el.control_evidence.original_filename}")
                    # Add actual file if exists
                    if el.control_evidence.stored_path and os.path.exists(el.control_evidence.stored_path):
                        arcname = f"{req.requirement_reference or 'misc'}/{el.control_evidence.original_filename}"
                        zf.write(el.control_evidence.stored_path, arcname)
                elif el.evidence_type == "POLICY" and el.policy:
                    evidence_items.append(f"Policy: {el.policy.policy_ref} - {el.policy.title}")
                elif el.evidence_type == "VENDOR_DOCUMENT" and el.vendor_document:
                    evidence_items.append(f"Vendor Doc: {el.vendor_document.file_name}")
                elif el.evidence_type == "MANUAL_UPLOAD" and el.manual_filename:
                    evidence_items.append(f"Upload: {el.manual_filename}")
                    if el.manual_stored_path and os.path.exists(el.manual_stored_path):
                        arcname = f"{req.requirement_reference or 'misc'}/{el.manual_filename}"
                        zf.write(el.manual_stored_path, arcname)

            req_rows.append({
                "ref": req.requirement_reference or "",
                "title": req.request_title,
                "status": req.status,
                "evidence": evidence_items,
            })

        # Generate index.html
        total = len(project.requests)
        accepted = sum(1 for r in project.requests if r.status == "ACCEPTED")
        provided = sum(1 for r in project.requests if r.status == "PROVIDED")
        with_evidence = sum(1 for r in project.requests if len(r.evidence_links) > 0)

        evidence_rows_html = ""
        for row in req_rows:
            ev_html = "<br>".join(row["evidence"]) if row["evidence"] else "<em>No evidence</em>"
            status_color = {"ACCEPTED": "#198754", "PROVIDED": "#ffc107", "OPEN": "#6c757d"}.get(row["status"], "#6c757d")
            evidence_rows_html += f"""<tr>
                <td>{row['ref']}</td>
                <td>{row['title']}</td>
                <td><span style="color:{status_color};font-weight:bold;">{row['status']}</span></td>
                <td>{ev_html}</td>
            </tr>"""

        index_html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Audit Evidence Binder - {project.title}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 40px; color: #333; }}
h1 {{ color: #1a1a2e; border-bottom: 3px solid #0d6efd; padding-bottom: 10px; }}
.meta {{ background: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0; }}
.meta dt {{ font-weight: bold; color: #555; }}
.kpi {{ display: flex; gap: 20px; margin: 20px 0; }}
.kpi-card {{ background: #fff; border: 1px solid #dee2e6; border-radius: 8px; padding: 15px 25px; text-align: center; }}
.kpi-card .num {{ font-size: 2rem; font-weight: bold; color: #0d6efd; }}
.kpi-card .label {{ color: #6c757d; font-size: 0.85rem; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
th {{ background: #1a1a2e; color: white; padding: 10px; text-align: left; }}
td {{ padding: 8px 10px; border-bottom: 1px solid #dee2e6; vertical-align: top; }}
tr:hover {{ background: #f8f9fa; }}
</style></head><body>
<h1>Audit Evidence Binder</h1>
<div class="meta">
<dl>
<dt>Project</dt><dd>{project.title}</dd>
<dt>Framework</dt><dd>{project.framework}</dd>
<dt>Auditor</dt><dd>{project.auditor_name or 'N/A'} — {project.auditor_firm or 'N/A'}</dd>
<dt>Audit Period</dt><dd>{project.audit_period_start.strftime('%Y-%m-%d') if project.audit_period_start else 'N/A'} to {project.audit_period_end.strftime('%Y-%m-%d') if project.audit_period_end else 'N/A'}</dd>
<dt>Generated</dt><dd>{datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</dd>
</dl></div>
<div class="kpi">
<div class="kpi-card"><div class="num">{total}</div><div class="label">Total Requests</div></div>
<div class="kpi-card"><div class="num">{accepted}</div><div class="label">Accepted</div></div>
<div class="kpi-card"><div class="num">{provided}</div><div class="label">Provided</div></div>
<div class="kpi-card"><div class="num">{with_evidence}</div><div class="label">With Evidence</div></div>
</div>
<h2>Evidence Inventory</h2>
<table>
<thead><tr><th>Reference</th><th>Request</th><th>Status</th><th>Evidence</th></tr></thead>
<tbody>{evidence_rows_html}</tbody>
</table>
</body></html>"""
        zf.writestr("index.html", index_html)

    return zip_path
