"""Controls module — library, implementations, testing, dashboard, gap analysis."""

from fastapi import APIRouter, Request, Form, Depends, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, Response
from sqlalchemy.orm import Session
from urllib.parse import quote
from datetime import datetime

from app import templates
from models import (
    get_db, User, Vendor, Control, ControlImplementation, ControlFinding,
    ControlTest, ControlAttestation,
    QuestionBankItem, RiskStatement,
    AVAILABLE_FRAMEWORKS, FRAMEWORK_DISPLAY, VALID_CONTROL_DOMAINS,
    VALID_CONTROL_TYPES, CONTROL_TYPE_LABELS,
    VALID_CONTROL_IMPL_TYPES, CONTROL_IMPL_TYPE_LABELS,
    VALID_CONTROL_FREQUENCIES, CONTROL_FREQUENCY_LABELS,
    VALID_CONTROL_CRITICALITIES,
    VALID_IMPL_STATUSES, IMPL_STATUS_LABELS, IMPL_STATUS_COLORS,
    VALID_EFFECTIVENESS_LEVELS, EFFECTIVENESS_LABELS, EFFECTIVENESS_COLORS,
    VALID_TEST_TYPES, TEST_TYPE_LABELS,
    VALID_TEST_RESULTS, TEST_RESULT_LABELS, TEST_RESULT_COLORS,
    TEST_STATUS_SCHEDULED, TEST_STATUS_IN_PROGRESS, TEST_STATUS_COMPLETED,
    TEST_STATUS_LABELS, TEST_STATUS_COLORS,
    IMPL_STATUS_IMPLEMENTED,
    VALID_FINDING_RISK_RATINGS, FINDING_RISK_LABELS, FINDING_RISK_COLORS,
    VALID_FINDING_TYPES, FINDING_TYPE_LABELS,
    VALID_FINDING_STATUSES, FINDING_STATUS_LABELS, FINDING_STATUS_COLORS,
    FINDING_STATUS_OPEN, FINDING_STATUS_IN_PROGRESS as FINDING_STATUS_IP,
    VALID_SEVERITIES,
    VALID_ATTESTATION_STATUSES, ATTESTATION_STATUS_LABELS, ATTESTATION_STATUS_COLORS,
    ATTESTATION_STATUS_PENDING,
    AUDIT_ACTION_CREATE, AUDIT_ACTION_UPDATE, AUDIT_ACTION_DELETE,
    AUDIT_ENTITY_CONTROL, AUDIT_ENTITY_CONTROL_IMPL,
)
from app.services.auth_service import require_role, require_login
from app.services.audit_service import log_audit
from app.services import control_service as svc
from app.services import control_dashboard_service as dash_svc
from app.services.export_service import generate_control_test_pdf, generate_testing_summary_csv
from app.services.health_score_service import compute_health_score, compute_readiness, compute_health_scores_bulk
from app.services.health_score_service import record_health_snapshot, record_all_health_snapshots, get_health_trend, get_portfolio_health_trend
from app.services import attestation_service as att_svc
from app.services import control_notification_service as notif_svc

router = APIRouter()
_analyst_dep = require_role("admin", "analyst")


# ==================== CONTROL LIBRARY ====================

@router.get("/controls", response_class=HTMLResponse)
async def control_library(
    request: Request,
    domain: str = "",
    framework: str = "",
    control_type: str = "",
    criticality: str = "",
    owner: str = "",
    impl_status: str = "",
    health: str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    controls = svc.get_all_controls(db, active_only=True)

    if domain:
        controls = [c for c in controls if c.domain == domain]
    if framework:
        from models import ControlFrameworkMapping
        fw_ctrl_ids = {m.control_id for m in db.query(ControlFrameworkMapping).filter_by(framework=framework).all()}
        controls = [c for c in controls if c.id in fw_ctrl_ids]
    if control_type:
        controls = [c for c in controls if c.control_type == control_type]
    if criticality:
        controls = [c for c in controls if c.criticality == criticality]
    if owner:
        owner_int = int(owner) if owner.isdigit() else None
        controls = [c for c in controls if c.owner_user_id == owner_int]

    # Build impl status map for all controls (org-level implementations)
    control_ids = [c.id for c in controls]
    org_impls = db.query(ControlImplementation).filter(
        ControlImplementation.vendor_id == None,
        ControlImplementation.control_id.in_(control_ids) if control_ids else False,
    ).all()
    impl_status_map = {i.control_id: i.status for i in org_impls}
    impl_id_map = {i.control_id: i.id for i in org_impls}

    # Compute health scores for org impls
    health_scores = compute_health_scores_bulk(db, org_impls) if org_impls else {}
    health_map = {}
    for impl in org_impls:
        h = health_scores.get(impl.id)
        if h:
            health_map[impl.control_id] = h

    # Apply impl_status filter
    if impl_status:
        if impl_status == "NOT_TRACKED":
            controls = [c for c in controls if c.id not in impl_status_map]
        else:
            controls = [c for c in controls if impl_status_map.get(c.id) == impl_status]

    # Apply health filter
    if health:
        thresholds = {"healthy": (80, 101), "adequate": (60, 80), "at_risk": (40, 60), "critical": (0, 40)}
        lo, hi = thresholds.get(health, (0, 101))
        controls = [c for c in controls if health_map.get(c.id) and lo <= health_map[c.id]["score"] < hi]

    grouped = {}
    for c in controls:
        grouped.setdefault(c.domain, []).append(c)

    stats = svc.get_control_library_stats(db)

    control_ids = [c.id for c in controls]
    last_tested_map = svc.get_last_tested_dates(db, control_ids)

    users = db.query(User).filter(User.is_active == True).order_by(User.display_name).all()

    return templates.TemplateResponse("control_library.html", {
        "request": request,
        "grouped": grouped,
        "stats": stats,
        "total_count": len(controls),
        "last_tested_map": last_tested_map,
        "impl_status_map": impl_status_map,
        "health_map": health_map,
        "domains": VALID_CONTROL_DOMAINS,
        "frameworks": AVAILABLE_FRAMEWORKS,
        "framework_display": FRAMEWORK_DISPLAY,
        "control_types": VALID_CONTROL_TYPES,
        "control_type_labels": CONTROL_TYPE_LABELS,
        "criticalities": VALID_CONTROL_CRITICALITIES,
        "frequency_labels": CONTROL_FREQUENCY_LABELS,
        "impl_type_labels": CONTROL_IMPL_TYPE_LABELS,
        "impl_statuses": VALID_IMPL_STATUSES,
        "impl_status_labels": IMPL_STATUS_LABELS,
        "impl_status_colors": IMPL_STATUS_COLORS,
        "users": users,
        "f_domain": domain,
        "f_framework": framework,
        "f_control_type": control_type,
        "f_criticality": criticality,
        "f_owner": owner,
        "f_impl_status": impl_status,
        "f_health": health,
    })


@router.get("/controls/new", response_class=HTMLResponse)
async def control_new(request: Request, db: Session = Depends(get_db), current_user: User = Depends(_analyst_dep)):
    ctx = _form_context(db)
    ctx["request"] = request
    return templates.TemplateResponse("control_form.html", ctx)


@router.post("/controls/new", response_class=HTMLResponse)
async def control_create(
    request: Request,
    control_ref: str = Form(...),
    title: str = Form(...),
    description: str = Form(""),
    domain: str = Form(...),
    control_type: str = Form(...),
    implementation_type: str = Form(...),
    test_frequency: str = Form(...),
    criticality: str = Form(...),
    owner_role: str = Form(""),
    objective: str = Form(""),
    procedure: str = Form(""),
    operation_frequency: str = Form(""),
    owner_user_id: str = Form(""),
    default_test_procedure: str = Form(""),
    evidence_instructions: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    existing = db.query(Control).filter(Control.control_ref == control_ref.strip()).first()
    if existing:
        ctx = _form_context(db, error="A control with that reference already exists.")
        ctx["request"] = request
        return templates.TemplateResponse("control_form.html", ctx)

    ctrl = svc.create_control(
        db, control_ref=control_ref.strip(), title=title.strip(),
        description=description.strip(), domain=domain, control_type=control_type,
        implementation_type=implementation_type, test_frequency=test_frequency,
        criticality=criticality, owner_role=owner_role.strip() or None,
        objective=objective.strip() or None,
        procedure=procedure.strip() or None,
        operation_frequency=operation_frequency.strip() or None,
        owner_user_id=int(owner_user_id) if owner_user_id.strip() else None,
        default_test_procedure=default_test_procedure.strip() or None,
        evidence_instructions=evidence_instructions.strip() or None,
    )

    form = await request.form()
    _save_mappings(db, ctrl.id, form)

    log_audit(db, AUDIT_ACTION_CREATE, AUDIT_ENTITY_CONTROL,
              entity_id=ctrl.id, entity_label=ctrl.control_ref,
              description=f"Created control {ctrl.control_ref}: {ctrl.title}",
              actor_user=current_user)
    db.commit()

    return RedirectResponse(url=f"/controls?message={quote('Control created')}&message_type=success", status_code=303)


@router.post("/controls/quick-add", response_class=HTMLResponse)
async def control_quick_add(
    request: Request,
    control_ref: str = Form(...),
    title: str = Form(...),
    domain: str = Form(...),
    criticality: str = Form("HIGH"),
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    existing = db.query(Control).filter(Control.control_ref == control_ref.strip()).first()
    if existing:
        return RedirectResponse(
            url=f"/controls?message={quote('A control with that reference already exists')}&message_type=danger",
            status_code=303,
        )

    ctrl = svc.create_control(
        db, control_ref=control_ref.strip(), title=title.strip(),
        domain=domain, criticality=criticality,
        control_type="PREVENTIVE", implementation_type="MANUAL",
        test_frequency="ANNUAL",
    )
    log_audit(db, AUDIT_ACTION_CREATE, AUDIT_ENTITY_CONTROL,
              entity_id=ctrl.id, entity_label=ctrl.control_ref,
              description=f"Quick-added control {ctrl.control_ref}: {ctrl.title}",
              actor_user=current_user)
    db.commit()

    return RedirectResponse(url=f"/controls?message={quote('Control created')}&message_type=success", status_code=303)


@router.get("/controls/dashboard", response_class=HTMLResponse)
async def control_dashboard(request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_login)):
    data = dash_svc.get_control_dashboard_data(db)

    # Health scores for all org-level implementations
    from models import ControlImplementation as CI
    org_impls = db.query(CI).filter(CI.vendor_id == None).all()
    health_scores = compute_health_scores_bulk(db, org_impls) if org_impls else {}
    avg_health = round(sum(h["score"] for h in health_scores.values()) / len(health_scores)) if health_scores else 0
    health_distribution = {"healthy": 0, "adequate": 0, "at_risk": 0, "critical": 0}
    for h in health_scores.values():
        if h["score"] >= 80:
            health_distribution["healthy"] += 1
        elif h["score"] >= 60:
            health_distribution["adequate"] += 1
        elif h["score"] >= 40:
            health_distribution["at_risk"] += 1
        else:
            health_distribution["critical"] += 1

    # Open findings count
    open_findings = svc.get_open_findings(db)

    # Action items (Feature 8)
    action_items = notif_svc.get_control_action_items(db)

    # Test results timeline (Feature 9)
    test_timeline = svc.get_test_results_timeline(db)

    # Portfolio health trend (Feature 11)
    portfolio_trend = get_portfolio_health_trend(db)

    return templates.TemplateResponse("control_dashboard.html", {
        "request": request,
        "current_user": current_user,
        "data": data,
        "avg_health": avg_health,
        "health_distribution": health_distribution,
        "open_findings_count": len(open_findings),
        "action_items": action_items,
        "test_timeline": test_timeline,
        "portfolio_trend": portfolio_trend,
        "framework_display": FRAMEWORK_DISPLAY,
        "test_result_labels": TEST_RESULT_LABELS,
        "test_result_colors": TEST_RESULT_COLORS,
        "test_type_labels": TEST_TYPE_LABELS,
    })


# ==================== FRAMEWORK BROWSER ====================

@router.get("/controls/frameworks", response_class=HTMLResponse)
async def framework_browser(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    from app.services import framework_service as fw_svc
    framework_stats = fw_svc.get_framework_stats(db)
    return templates.TemplateResponse("framework_browser.html", {
        "request": request,
        "framework_stats": framework_stats,
    })


@router.get("/controls/frameworks/cross-map", response_class=HTMLResponse)
async def framework_cross_map(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    from app.services import framework_service as fw_svc
    from models import SEEDED_FRAMEWORKS
    cross_mappings = fw_svc.get_cross_framework_mappings(db)
    return templates.TemplateResponse("framework_cross_map.html", {
        "request": request,
        "cross_mappings": cross_mappings,
        "frameworks": AVAILABLE_FRAMEWORKS,
        "seeded_frameworks": SEEDED_FRAMEWORKS,
    })


# ==================== CUSTOM FRAMEWORK MANAGEMENT ====================

@router.get("/controls/frameworks/new", response_class=HTMLResponse)
async def framework_new_form(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    return templates.TemplateResponse("framework_form.html", {
        "request": request,
        "framework": None,
    })


@router.post("/controls/frameworks/new", response_class=HTMLResponse)
async def framework_create(
    request: Request,
    display_name: str = Form(...),
    description: str = Form(None),
    version: str = Form(None),
    source_url: str = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    from app.services import framework_service as fw_svc
    from models import AUDIT_ACTION_CREATE, AUDIT_ENTITY_CUSTOM_FRAMEWORK
    fw = fw_svc.create_custom_framework(
        db, name=display_name, description=description,
        version=version, source_url=source_url, user_id=current_user.id,
    )
    log_audit(db, action=AUDIT_ACTION_CREATE, entity_type=AUDIT_ENTITY_CUSTOM_FRAMEWORK,
              entity_id=fw.id, entity_label=fw.framework_key,
              new_value={"display_name": display_name}, actor_user=current_user)
    db.commit()
    return RedirectResponse(url=f"/controls/frameworks/{fw.framework_key}", status_code=303)


@router.get("/controls/frameworks/{framework_key}", response_class=HTMLResponse)
async def framework_detail(
    request: Request,
    framework_key: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    from app.services import framework_service as fw_svc
    from models import ADOPTION_STATUS_MAPPED, ADOPTION_STATUS_NOT_APPLICABLE, IMPL_STATUS_IMPLEMENTED

    fw_display = fw_svc.get_framework_display_dynamic(db)
    fw_label = fw_display.get(framework_key, framework_key)
    is_custom = fw_svc.is_custom_framework(db, framework_key)
    grouped = fw_svc.get_requirements_grouped(db, framework_key)
    coverage = fw_svc.get_requirement_coverage(db, framework_key)
    category_stats = fw_svc.get_category_coverage_stats(db, framework_key)
    all_controls = svc.get_all_controls(db, active_only=True)

    # Build coverage map keyed by reference
    coverage_map = {}
    mapped_count = 0
    na_count = 0
    implemented_count = 0
    for item in coverage:
        req = item["requirement"]
        coverage_map[req.reference] = item
        if item["status"] == ADOPTION_STATUS_MAPPED:
            mapped_count += 1
            if item["impl_status"] == IMPL_STATUS_IMPLEMENTED:
                implemented_count += 1
        elif item["status"] == ADOPTION_STATUS_NOT_APPLICABLE:
            na_count += 1

    total_reqs = len(coverage)
    gap_count = total_reqs - mapped_count - na_count

    return templates.TemplateResponse("framework_detail.html", {
        "request": request,
        "framework_key": framework_key,
        "fw_label": fw_label,
        "is_custom": is_custom,
        "grouped": grouped,
        "coverage_map": coverage_map,
        "category_stats": category_stats,
        "all_controls": all_controls,
        "total_reqs": total_reqs,
        "mapped_count": mapped_count,
        "na_count": na_count,
        "gap_count": gap_count,
        "implemented_count": implemented_count,
        "framework_display": fw_display,
    })


@router.get("/controls/frameworks/{framework_key}/requirements/{req_id}/edit", response_class=HTMLResponse)
async def framework_requirement_edit(
    request: Request,
    framework_key: str,
    req_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    from app.services import framework_service as fw_svc
    req = fw_svc.get_requirement_by_id(db, req_id)
    if not req or req.framework != framework_key:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse("framework_requirement_form.html", {
        "request": request,
        "req": req,
        "framework_display": FRAMEWORK_DISPLAY,
        "domains": VALID_CONTROL_DOMAINS,
        "control_types": VALID_CONTROL_TYPES,
        "control_type_labels": CONTROL_TYPE_LABELS,
    })


@router.post("/controls/frameworks/{framework_key}/requirements/{req_id}/edit", response_class=HTMLResponse)
async def framework_requirement_save(
    request: Request,
    framework_key: str,
    req_id: int,
    title: str = Form(...),
    description: str = Form(""),
    guidance: str = Form(""),
    category: str = Form(""),
    subcategory: str = Form(""),
    suggested_domain: str = Form(""),
    suggested_control_type: str = Form(""),
    sort_order: int = Form(0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    from app.services import framework_service as fw_svc
    fw_svc.update_requirement(db, req_id,
        title=title.strip(),
        description=description.strip() or None,
        guidance=guidance.strip() or None,
        category=category.strip() or None,
        subcategory=subcategory.strip() or None,
        suggested_domain=suggested_domain or None,
        suggested_control_type=suggested_control_type or None,
        sort_order=sort_order,
    )
    db.commit()
    return RedirectResponse(
        url=f"/controls/frameworks/{framework_key}?message={quote('Requirement updated')}&message_type=success",
        status_code=303,
    )


@router.post("/controls/frameworks/{framework_key}/requirements/{req_id}/toggle", response_class=HTMLResponse)
async def framework_requirement_toggle(
    request: Request,
    framework_key: str,
    req_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    from app.services import framework_service as fw_svc
    req = fw_svc.get_requirement_by_id(db, req_id)
    if not req:
        raise HTTPException(status_code=404)
    fw_svc.update_requirement(db, req_id, is_active=not req.is_active)
    db.commit()
    status = "activated" if not req.is_active else "deactivated"
    return RedirectResponse(
        url=f"/controls/frameworks/{framework_key}?message={quote(f'Requirement {status}')}&message_type=success",
        status_code=303,
    )


# ==================== ADOPTION WORKFLOW ====================

@router.post("/controls/frameworks/{framework_key}/requirements/{req_id}/link-control", response_class=HTMLResponse)
async def framework_link_control(
    request: Request,
    framework_key: str,
    req_id: int,
    control_id: int = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    from app.services import framework_service as fw_svc
    req = fw_svc.get_requirement_by_id(db, req_id)
    if not req or req.framework != framework_key:
        raise HTTPException(status_code=404)
    fw_svc.adopt_requirement_mapped(db, framework_key, req.reference, control_id, current_user.id)
    db.commit()
    return RedirectResponse(
        url=f"/controls/frameworks/{framework_key}?message={quote(f'{req.reference} linked to control')}&message_type=success",
        status_code=303,
    )


@router.post("/controls/frameworks/{framework_key}/requirements/{req_id}/auto-create", response_class=HTMLResponse)
async def framework_auto_create(
    request: Request,
    framework_key: str,
    req_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    from app.services import framework_service as fw_svc
    req = fw_svc.get_requirement_by_id(db, req_id)
    if not req or req.framework != framework_key:
        raise HTTPException(status_code=404)
    ctrl = fw_svc.auto_create_control_from_requirement(db, req, current_user.id)
    db.commit()
    return RedirectResponse(
        url=f"/controls/frameworks/{framework_key}?message={quote(f'Created {ctrl.control_ref} for {req.reference}')}&message_type=success",
        status_code=303,
    )


@router.post("/controls/frameworks/{framework_key}/requirements/{req_id}/mark-na", response_class=HTMLResponse)
async def framework_mark_na(
    request: Request,
    framework_key: str,
    req_id: int,
    notes: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    from app.services import framework_service as fw_svc
    req = fw_svc.get_requirement_by_id(db, req_id)
    if not req or req.framework != framework_key:
        raise HTTPException(status_code=404)
    fw_svc.adopt_requirement_as_na(db, framework_key, req.reference, current_user.id, notes.strip())
    db.commit()
    return RedirectResponse(
        url=f"/controls/frameworks/{framework_key}?message={quote(f'{req.reference} marked N/A')}&message_type=success",
        status_code=303,
    )


@router.post("/controls/frameworks/{framework_key}/requirements/{req_id}/unlink", response_class=HTMLResponse)
async def framework_unlink(
    request: Request,
    framework_key: str,
    req_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    from app.services import framework_service as fw_svc
    req = fw_svc.get_requirement_by_id(db, req_id)
    if not req or req.framework != framework_key:
        raise HTTPException(status_code=404)
    fw_svc.unadopt_requirement(db, framework_key, req.reference)
    db.commit()
    return RedirectResponse(
        url=f"/controls/frameworks/{framework_key}?message={quote(f'{req.reference} reset to Not Addressed')}&message_type=success",
        status_code=303,
    )


@router.post("/controls/frameworks/{framework_key}/adopt-all", response_class=HTMLResponse)
async def framework_adopt_all(
    request: Request,
    framework_key: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    from app.services import framework_service as fw_svc
    result = fw_svc.bulk_adopt_unmapped(db, framework_key, current_user.id)
    db.commit()
    msg = f"Created {result['created']} controls ({result['skipped']} already addressed)"
    return RedirectResponse(
        url=f"/controls/frameworks/{framework_key}?message={quote(msg)}&message_type=success",
        status_code=303,
    )


# ==================== GAP ANALYSIS (ENHANCED) ====================

@router.get("/controls/gap-analysis", response_class=HTMLResponse)
async def gap_analysis(
    request: Request,
    framework: str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    from app.services.control_dashboard_service import get_framework_coverage
    from app.services import framework_service as fw_svc
    from models import FrameworkRequirement, SEEDED_FRAMEWORKS, ADOPTION_STATUS_MAPPED, ADOPTION_STATUS_NOT_APPLICABLE

    fw_coverage = get_framework_coverage(db)

    # Check if selected framework has seeded requirements
    has_seeded_reqs = False
    coverage_data = []
    category_stats = []
    legacy_gaps = []
    kpis = {}

    if framework:
        req_count = fw_svc.get_requirement_count(db, framework)
        has_seeded_reqs = req_count > 0

        if has_seeded_reqs:
            coverage_data = fw_svc.get_requirement_coverage(db, framework)
            category_stats = fw_svc.get_category_coverage_stats(db, framework)
            mapped = sum(1 for c in coverage_data if c["status"] == ADOPTION_STATUS_MAPPED)
            na = sum(1 for c in coverage_data if c["status"] == ADOPTION_STATUS_NOT_APPLICABLE)
            impl = sum(1 for c in coverage_data if c["status"] == ADOPTION_STATUS_MAPPED and c["impl_status"] == "IMPLEMENTED")
            kpis = {
                "total": len(coverage_data),
                "mapped": mapped,
                "na": na,
                "gaps": len(coverage_data) - mapped - na,
                "implemented": impl,
                "mapped_pct": round(mapped / len(coverage_data) * 100) if coverage_data else 0,
                "impl_pct": round(impl / len(coverage_data) * 100) if coverage_data else 0,
            }
        else:
            # Legacy fallback for non-seeded frameworks
            controls_with_refs = svc.get_controls_by_framework(db, framework)
            for ctrl, ref in controls_with_refs:
                org_impl = db.query(ControlImplementation).filter(
                    ControlImplementation.control_id == ctrl.id,
                    ControlImplementation.vendor_id == None,
                ).first()
                legacy_gaps.append({
                    "control": ctrl,
                    "reference": ref,
                    "implementation": org_impl,
                    "status": org_impl.status if org_impl else "NOT_TRACKED",
                })

    return templates.TemplateResponse("gap_analysis.html", {
        "request": request,
        "framework": framework,
        "f_framework": framework,
        "has_seeded_reqs": has_seeded_reqs,
        "coverage_data": coverage_data,
        "category_stats": category_stats,
        "kpis": kpis,
        "gaps": legacy_gaps,
        "fw_coverage": fw_coverage,
        "frameworks": AVAILABLE_FRAMEWORKS,
        "framework_display": FRAMEWORK_DISPLAY,
        "impl_status_labels": IMPL_STATUS_LABELS,
        "impl_status_colors": IMPL_STATUS_COLORS,
        "seeded_frameworks": SEEDED_FRAMEWORKS,
    })


@router.get("/controls/gap-analysis/export", response_class=Response)
async def gap_analysis_export(
    request: Request,
    framework: str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    if not framework:
        raise HTTPException(status_code=400, detail="Framework parameter required")
    from app.services import framework_service as fw_svc
    csv_content = fw_svc.export_gap_analysis_csv(db, framework)
    fw_label = FRAMEWORK_DISPLAY.get(framework, framework).replace(" ", "_")
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=gap_analysis_{fw_label}.csv"},
    )


@router.get("/controls/testing", response_class=HTMLResponse)
async def control_testing_tracker(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    from datetime import timedelta
    now = datetime.utcnow()
    thirty_days = now + timedelta(days=30)

    # Schedule: all implemented controls with testing obligations
    schedule_impls = svc.get_all_testing_schedule(db)
    impl_ids_for_last_tested = list({impl.control_id for impl in schedule_impls})
    last_tested_map = svc.get_last_tested_dates(db, impl_ids_for_last_tested)

    # Per-implementation last tested (more granular than per-control)
    from sqlalchemy import func as sa_func
    from models import ControlTest as CT
    impl_last_tested_rows = db.query(
        CT.implementation_id, sa_func.max(CT.test_date),
    ).filter(
        CT.implementation_id.in_([i.id for i in schedule_impls]) if schedule_impls else False,
    ).group_by(CT.implementation_id).all()
    impl_last_tested = {iid: dt for iid, dt in impl_last_tested_rows}

    schedule_rows = []
    for impl in schedule_impls:
        last_tested = impl_last_tested.get(impl.id)
        next_due = impl.next_test_date
        if next_due:
            delta = (next_due - now).days
            if delta < 0:
                testing_status = "OVERDUE"
            elif delta <= 30:
                testing_status = "UPCOMING"
            else:
                testing_status = "ON_TRACK"
            days_until_due = delta
        else:
            testing_status = "NEVER_TESTED"
            days_until_due = None

        schedule_rows.append({
            "impl": impl,
            "testing_status": testing_status,
            "last_tested": last_tested,
            "days_until_due": days_until_due,
        })

    # Test history
    test_history = svc.get_all_test_history(db)

    # KPIs
    testing_summary = dash_svc.get_testing_status_summary(db)
    month_start = datetime(now.year, now.month, 1)
    completed_this_month = sum(
        1 for t in test_history if t.test_date and t.test_date >= month_start
    )
    year_start = datetime(now.year, 1, 1)
    ytd_tests = [t for t in test_history if t.test_date and t.test_date >= year_start]
    ytd_total = len(ytd_tests)
    from models import TEST_RESULT_PASS
    ytd_pass = sum(1 for t in ytd_tests if t.result == TEST_RESULT_PASS)
    pass_rate_ytd = round(ytd_pass / ytd_total * 100) if ytd_total > 0 else 0

    # Scheduled tests
    scheduled_tests = svc.get_scheduled_tests(db)

    # In-progress tests
    in_progress_tests = svc.get_in_progress_tests(db)

    # Build lookup: impl_id → list of scheduled tests
    scheduled_by_impl = {}
    for st in scheduled_tests:
        scheduled_by_impl.setdefault(st.implementation_id, []).append(st)

    # Filter reference data
    users = db.query(User).filter(User.is_active == True).order_by(User.display_name).all()

    # All active controls for the schedule modal (user picks any control)
    all_controls = svc.get_all_controls(db, active_only=True)

    # Pre-select implementation for schedule modal (from ?schedule=<impl_id>)
    pre_select_impl = request.query_params.get("schedule", "")

    return templates.TemplateResponse("control_testing.html", {
        "request": request,
        "schedule_rows": schedule_rows,
        "scheduled_tests": scheduled_tests,
        "in_progress_tests": in_progress_tests,
        "scheduled_by_impl": scheduled_by_impl,
        "test_history": test_history,
        "kpi_overdue": testing_summary["overdue"],
        "kpi_upcoming": testing_summary["upcoming"],
        "kpi_scheduled": len(scheduled_tests),
        "kpi_in_progress": len(in_progress_tests),
        "kpi_completed_month": completed_this_month,
        "kpi_pass_rate": pass_rate_ytd,
        "domains": VALID_CONTROL_DOMAINS,
        "users": users,
        "all_controls": all_controls,
        "all_implementations": schedule_impls,
        "test_types": VALID_TEST_TYPES,
        "test_type_labels": TEST_TYPE_LABELS,
        "test_results": VALID_TEST_RESULTS,
        "test_result_labels": TEST_RESULT_LABELS,
        "test_result_colors": TEST_RESULT_COLORS,
        "finding_risk_labels": FINDING_RISK_LABELS,
        "finding_risk_colors": FINDING_RISK_COLORS,
        "frequency_labels": CONTROL_FREQUENCY_LABELS,
        "pre_select_impl": pre_select_impl,
    })


@router.post("/controls/testing/schedule", response_class=HTMLResponse)
async def control_test_schedule(
    request: Request,
    control_id: int = Form(...),
    test_type: str = Form(...),
    scheduled_date: str = Form(...),
    tester_user_id: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    ctrl = db.query(Control).filter(Control.id == control_id).first()
    if not ctrl:
        raise HTTPException(status_code=404, detail="Control not found")

    # Find or create org-level implementation
    impl = db.query(ControlImplementation).filter(
        ControlImplementation.control_id == control_id,
        ControlImplementation.vendor_id == None,
    ).first()
    if not impl:
        impl = svc.create_implementation(db, control_id)
        impl.status = IMPL_STATUS_IMPLEMENTED
        db.flush()

    sched_dt = datetime.strptime(scheduled_date.strip(), "%Y-%m-%d")
    tester_id = int(tester_user_id) if tester_user_id.strip() else None
    test = svc.create_scheduled_test(db, impl.id, test_type, sched_dt, tester_id)

    log_audit(db, AUDIT_ACTION_CREATE, "control_test",
              entity_id=test.id,
              entity_label=f"Scheduled test for {ctrl.control_ref}",
              description=f"Scheduled {test_type} test for {scheduled_date}",
              actor_user=current_user)
    db.commit()

    return RedirectResponse(
        url=f"/controls/testing?message={quote('Test scheduled')}&message_type=success",
        status_code=303,
    )


@router.post("/controls/testing/bulk-schedule", response_class=HTMLResponse)
async def control_test_bulk_schedule(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    """Bulk-schedule tests for multiple implementations."""
    form = await request.form()
    impl_ids = [int(v) for k, v in form.multi_items() if k == "impl_ids"]
    test_type = form.get("test_type", "OPERATING")
    scheduled_date = form.get("scheduled_date", "")
    tester_user_id = form.get("tester_user_id", "")

    if not impl_ids or not scheduled_date.strip():
        return RedirectResponse(
            url=f"/controls/testing?message={quote('Missing required fields')}&message_type=warning",
            status_code=303,
        )

    sched_dt = datetime.strptime(scheduled_date.strip(), "%Y-%m-%d")
    tester_id = int(tester_user_id) if tester_user_id.strip() else None
    count = 0
    for iid in impl_ids:
        impl = db.query(ControlImplementation).filter(ControlImplementation.id == iid).first()
        if impl:
            svc.create_scheduled_test(db, iid, test_type, sched_dt, tester_id)
            count += 1

    log_audit(db, AUDIT_ACTION_CREATE, "control_test",
              entity_label=f"Bulk scheduled {count} tests",
              description=f"Bulk-scheduled {count} tests for {scheduled_date}",
              actor_user=current_user)
    db.commit()

    return RedirectResponse(
        url=f"/controls/testing?message={quote(f'Scheduled {count} tests')}&message_type=success",
        status_code=303,
    )


# ==================== TESTING EXPORT (Feature 20) ====================

@router.get("/controls/testing/export.csv")
async def control_testing_export_csv(
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    """Download all completed org-level test results as CSV."""
    csv_content = generate_testing_summary_csv(db)
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="testing_summary.csv"'},
    )


# ==================== PERSONAL WORK QUEUE & REGISTERS ====================


@router.get("/controls/my-work", response_class=HTMLResponse)
async def control_my_work(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_login),
):
    """Personal work queue -- controls I own, tests assigned to me, findings assigned to me, attestations pending."""
    from sqlalchemy.orm import joinedload as jl

    uid = current_user.id

    # Controls I own
    my_controls = db.query(Control).filter(
        Control.owner_user_id == uid,
        Control.is_active == True,
    ).order_by(Control.control_ref).all()

    # Tests assigned to me (scheduled + in-progress)
    my_tests = db.query(ControlTest).options(
        jl(ControlTest.implementation).joinedload(ControlImplementation.control),
    ).join(
        ControlImplementation, ControlTest.implementation_id == ControlImplementation.id
    ).filter(
        ControlTest.tester_user_id == uid,
        ControlTest.status.in_([TEST_STATUS_SCHEDULED, TEST_STATUS_IN_PROGRESS]),
        ControlImplementation.vendor_id == None,
    ).order_by(ControlTest.scheduled_date.asc().nullsfirst()).all()

    my_scheduled = [t for t in my_tests if t.status == TEST_STATUS_SCHEDULED]
    my_in_progress = [t for t in my_tests if t.status == TEST_STATUS_IN_PROGRESS]

    # Overdue tests for impls I own
    from datetime import datetime as dt_cls
    now = dt_cls.utcnow()
    my_overdue_impls = db.query(ControlImplementation).options(
        jl(ControlImplementation.control),
    ).filter(
        ControlImplementation.owner_user_id == uid,
        ControlImplementation.vendor_id == None,
        ControlImplementation.status == IMPL_STATUS_IMPLEMENTED,
        ControlImplementation.next_test_date != None,
        ControlImplementation.next_test_date < now,
    ).order_by(ControlImplementation.next_test_date.asc()).all()

    # Findings assigned to me (open/in-progress)
    my_findings = db.query(ControlFinding).options(
        jl(ControlFinding.test).joinedload(ControlTest.implementation).joinedload(ControlImplementation.control),
        jl(ControlFinding.owner),
    ).join(
        ControlTest, ControlFinding.control_test_id == ControlTest.id
    ).join(
        ControlImplementation, ControlTest.implementation_id == ControlImplementation.id
    ).filter(
        ControlFinding.owner_user_id == uid,
        ControlFinding.status.in_([FINDING_STATUS_OPEN, FINDING_STATUS_IP]),
        ControlImplementation.vendor_id == None,
    ).order_by(ControlFinding.due_date.asc().nullslast()).all()

    # Attestations pending for me
    my_attestations = db.query(ControlAttestation).options(
        jl(ControlAttestation.implementation).joinedload(ControlImplementation.control),
        jl(ControlAttestation.attestor),
    ).join(
        ControlImplementation, ControlAttestation.implementation_id == ControlImplementation.id
    ).filter(
        ControlAttestation.attestor_user_id == uid,
        ControlAttestation.status == ATTESTATION_STATUS_PENDING,
        ControlImplementation.vendor_id == None,
    ).order_by(ControlAttestation.due_date.asc().nullslast()).all()

    return templates.TemplateResponse("my_controls.html", {
        "request": request,
        "current_user": current_user,
        "my_controls": my_controls,
        "my_scheduled": my_scheduled,
        "my_in_progress": my_in_progress,
        "my_overdue_impls": my_overdue_impls,
        "my_findings": my_findings,
        "my_attestations": my_attestations,
        "finding_status_labels": FINDING_STATUS_LABELS,
        "finding_status_colors": FINDING_STATUS_COLORS,
        "finding_type_labels": FINDING_TYPE_LABELS,
        "test_type_labels": TEST_TYPE_LABELS,
        "attestation_status_labels": ATTESTATION_STATUS_LABELS,
        "attestation_status_colors": ATTESTATION_STATUS_COLORS,
        "frequency_labels": CONTROL_FREQUENCY_LABELS,
    })


@router.get("/controls/findings", response_class=HTMLResponse)
async def control_findings_register(
    request: Request,
    status: str = "",
    severity: str = "",
    owner: str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    """Cross-control findings register with server-side filtering."""
    findings = svc.get_all_findings(db)

    # Server-side filters
    if status:
        findings = [f for f in findings if f.status == status]
    if severity:
        findings = [f for f in findings if f.severity == severity]
    if owner:
        owner_int = int(owner) if owner.isdigit() else None
        findings = [f for f in findings if f.owner_user_id == owner_int]

    # KPIs (unfiltered)
    all_findings = svc.get_all_findings(db)
    from datetime import datetime as dt_cls
    now = dt_cls.utcnow()
    kpi_total = len(all_findings)
    kpi_open = sum(1 for f in all_findings if f.status == FINDING_STATUS_OPEN)
    kpi_in_progress = sum(1 for f in all_findings if f.status == FINDING_STATUS_IP)
    kpi_overdue = sum(1 for f in all_findings if f.status in (FINDING_STATUS_OPEN, FINDING_STATUS_IP) and f.due_date and f.due_date < now)
    month_start = dt_cls(now.year, now.month, 1)
    kpi_closed_month = sum(1 for f in all_findings if f.status == 'CLOSED' and f.closed_date and f.closed_date >= month_start)

    users = db.query(User).filter(User.is_active == True).order_by(User.display_name).all()

    return templates.TemplateResponse("findings_register.html", {
        "request": request,
        "current_user": current_user,
        "findings": findings,
        "kpi_total": kpi_total,
        "kpi_open": kpi_open,
        "kpi_in_progress": kpi_in_progress,
        "kpi_overdue": kpi_overdue,
        "kpi_closed_month": kpi_closed_month,
        "users": users,
        "finding_statuses": VALID_FINDING_STATUSES,
        "finding_status_labels": FINDING_STATUS_LABELS,
        "finding_status_colors": FINDING_STATUS_COLORS,
        "finding_types": VALID_FINDING_TYPES,
        "finding_type_labels": FINDING_TYPE_LABELS,
        "severities": VALID_SEVERITIES,
        "f_status": status,
        "f_severity": severity,
        "f_owner": owner,
    })


@router.get("/controls/attestations", response_class=HTMLResponse)
async def control_attestation_tracker(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    """Cross-control attestation tracker."""
    from sqlalchemy.orm import joinedload as jl

    attestations = db.query(ControlAttestation).options(
        jl(ControlAttestation.implementation).joinedload(ControlImplementation.control),
        jl(ControlAttestation.attestor),
    ).join(
        ControlImplementation, ControlAttestation.implementation_id == ControlImplementation.id
    ).filter(
        ControlImplementation.vendor_id == None,
    ).order_by(ControlAttestation.created_at.desc()).all()

    # KPIs
    from datetime import datetime as dt_cls
    now = dt_cls.utcnow()
    kpi_pending = sum(1 for a in attestations if a.status == ATTESTATION_STATUS_PENDING)
    kpi_overdue = sum(1 for a in attestations if a.status == ATTESTATION_STATUS_PENDING and a.due_date and a.due_date < now)
    kpi_attested = sum(1 for a in attestations if a.status == 'ATTESTED')
    kpi_rejected = sum(1 for a in attestations if a.status == 'REJECTED')

    users = db.query(User).filter(User.is_active == True).order_by(User.display_name).all()

    return templates.TemplateResponse("attestation_tracker.html", {
        "request": request,
        "current_user": current_user,
        "attestations": attestations,
        "kpi_pending": kpi_pending,
        "kpi_overdue": kpi_overdue,
        "kpi_attested": kpi_attested,
        "kpi_rejected": kpi_rejected,
        "users": users,
        "attestation_statuses": VALID_ATTESTATION_STATUSES,
        "attestation_status_labels": ATTESTATION_STATUS_LABELS,
        "attestation_status_colors": ATTESTATION_STATUS_COLORS,
    })


@router.post("/controls/tests/{test_id}/start", response_class=HTMLResponse)
async def control_test_start(
    test_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    """Transition a SCHEDULED test to IN_PROGRESS, then redirect to the workspace."""
    test = svc.get_test(db, test_id)
    if not test or test.status != TEST_STATUS_SCHEDULED:
        raise HTTPException(status_code=404, detail="Scheduled test not found")

    svc.start_test(db, test_id)

    log_audit(db, AUDIT_ACTION_UPDATE, "control_test",
              entity_id=test.id,
              entity_label=f"Started test for {test.implementation.control.control_ref}",
              description=f"Began working {test.test_type} test",
              actor_user=current_user)
    db.commit()

    return RedirectResponse(
        url=f"/controls/tests/{test_id}?message={quote('Test started — save your progress as you work')}&message_type=success",
        status_code=303,
    )


@router.post("/controls/tests/{test_id}/save", response_class=HTMLResponse)
async def control_test_save_progress(
    request: Request,
    test_id: int,
    test_type: str = Form(""),
    test_procedure: str = Form(""),
    result: str = Form(""),
    findings: str = Form(""),
    recommendations: str = Form(""),
    test_period_start: str = Form(""),
    test_period_end: str = Form(""),
    sample_size: str = Form(""),
    population_size: str = Form(""),
    exceptions_count: str = Form(""),
    exception_details: str = Form(""),
    conclusion: str = Form(""),
    finding_risk_rating: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    """Save work-in-progress on an IN_PROGRESS test."""
    test = svc.get_test(db, test_id)
    if not test or test.status != TEST_STATUS_IN_PROGRESS:
        raise HTTPException(status_code=404, detail="In-progress test not found")

    fields = {
        "test_procedure": test_procedure.strip() or None,
        "result": result.strip() or test.result,
        "findings": findings.strip() or None,
        "recommendations": recommendations.strip() or None,
        "exception_details": exception_details.strip() or None,
        "conclusion": conclusion.strip() or None,
        "finding_risk_rating": finding_risk_rating.strip() or None,
    }
    if test_type.strip():
        fields["test_type"] = test_type.strip()

    extra = _parse_enhanced_test_fields(
        test_period_start, test_period_end, sample_size, population_size,
        exceptions_count, "", "", "",
    )
    fields.update(extra)

    svc.save_test_progress(db, test_id, **fields)

    # Handle file uploads
    form = await request.form()
    files = form.getlist("evidence_files")
    uploaded = 0
    for f in files:
        if hasattr(f, 'filename') and f.filename:
            ev = await svc.store_control_evidence(f, test_id)
            db.add(ev)
            uploaded += 1

    db.commit()

    return RedirectResponse(
        url=f"/controls/tests/{test_id}?message={quote('Progress saved')}&message_type=success",
        status_code=303,
    )


@router.post("/controls/tests/{test_id}/finalize", response_class=HTMLResponse)
async def control_test_finalize(
    test_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    """Finalize an IN_PROGRESS test → COMPLETED."""
    test = svc.get_test(db, test_id)
    if not test or test.status != TEST_STATUS_IN_PROGRESS:
        raise HTTPException(status_code=404, detail="In-progress test not found")

    svc.finalize_test(db, test_id)

    # Record health snapshot on test finalization (Feature 11)
    if test.implementation:
        record_health_snapshot(db, test.implementation)

    log_audit(db, AUDIT_ACTION_UPDATE, "control_test",
              entity_id=test.id,
              entity_label=f"Finalized test for {test.implementation.control.control_ref}",
              description=f"Finalized {test.test_type} test: {test.result}",
              actor_user=current_user)
    db.commit()

    return RedirectResponse(
        url=f"/controls/tests/{test_id}?message={quote('Test finalized')}&message_type=success",
        status_code=303,
    )


@router.post("/controls/implementations/{impl_id}/set-test-date", response_class=HTMLResponse)
async def control_impl_set_test_date(
    impl_id: int,
    request: Request,
    next_test_date: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    impl = svc.get_implementation(db, impl_id)
    if not impl:
        raise HTTPException(status_code=404, detail="Implementation not found")

    if next_test_date.strip():
        dt = datetime.strptime(next_test_date.strip(), "%Y-%m-%d")
    else:
        dt = None
    svc.set_implementation_next_test_date(db, impl_id, dt)

    log_audit(db, AUDIT_ACTION_UPDATE, AUDIT_ENTITY_CONTROL_IMPL,
              entity_id=impl_id,
              entity_label=f"{impl.control.control_ref}",
              description=f"Set next test date to {next_test_date or 'none'}",
              actor_user=current_user)
    db.commit()

    referer = request.headers.get("referer", f"/controls/implementations/{impl_id}")
    return RedirectResponse(url=referer, status_code=303)


@router.post("/controls/{control_id}/toggle", response_class=HTMLResponse)
async def control_toggle(control_id: int, db: Session = Depends(get_db), current_user: User = Depends(_analyst_dep)):
    ctrl = db.query(Control).filter(Control.id == control_id).first()
    if not ctrl:
        raise HTTPException(status_code=404, detail="Control not found")

    ctrl.is_active = not ctrl.is_active
    new_state = "activated" if ctrl.is_active else "deactivated"
    log_audit(db, AUDIT_ACTION_UPDATE, AUDIT_ENTITY_CONTROL,
              entity_id=ctrl.id, entity_label=ctrl.control_ref,
              description=f"Control {ctrl.control_ref} {new_state}",
              actor_user=current_user)
    db.commit()

    return RedirectResponse(url=f"/controls?message={quote(f'Control {new_state}')}&message_type=success", status_code=303)


@router.get("/controls/{control_id}", response_class=HTMLResponse)
async def control_detail(request: Request, control_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_login)):
    ctrl = svc.get_control(db, control_id)
    if not ctrl:
        raise HTTPException(status_code=404, detail="Control not found")

    from sqlalchemy.orm import joinedload as jl
    impls = db.query(ControlImplementation).options(
        jl(ControlImplementation.owner),
    ).filter(
        ControlImplementation.control_id == control_id,
        ControlImplementation.vendor_id == None,
    ).all()

    # Check if org-level impl already exists (to show/hide Implement button)
    has_org_impl = any(True for i in impls)

    users = db.query(User).filter(User.is_active == True).order_by(User.display_name).all()

    last_tested_date = svc.get_last_tested_date(db, control_id)

    # Health scores for org implementations
    health_scores = compute_health_scores_bulk(db, impls) if impls else {}

    return templates.TemplateResponse("control_detail.html", {
        "request": request,
        "control": ctrl,
        "implementations": impls,
        "last_tested_date": last_tested_date,
        "has_org_impl": has_org_impl,
        "users": users,
        "health_scores": health_scores,
        "framework_display": FRAMEWORK_DISPLAY,
        "control_type_labels": CONTROL_TYPE_LABELS,
        "impl_type_labels": CONTROL_IMPL_TYPE_LABELS,
        "frequency_labels": CONTROL_FREQUENCY_LABELS,
        "impl_status_labels": IMPL_STATUS_LABELS,
        "impl_status_colors": IMPL_STATUS_COLORS,
        "effectiveness_labels": EFFECTIVENESS_LABELS,
        "effectiveness_colors": EFFECTIVENESS_COLORS,
        "IMPL_STATUS_IMPLEMENTED": IMPL_STATUS_IMPLEMENTED,
    })


@router.get("/controls/{control_id}/edit", response_class=HTMLResponse)
async def control_edit(request: Request, control_id: int, db: Session = Depends(get_db), current_user: User = Depends(_analyst_dep)):
    ctrl = svc.get_control(db, control_id)
    if not ctrl:
        raise HTTPException(status_code=404, detail="Control not found")

    ctx = _form_context(db, control=ctrl)
    ctx["request"] = request
    return templates.TemplateResponse("control_form.html", ctx)


@router.post("/controls/{control_id}/edit", response_class=HTMLResponse)
async def control_update(
    request: Request,
    control_id: int,
    control_ref: str = Form(...),
    title: str = Form(...),
    description: str = Form(""),
    domain: str = Form(...),
    control_type: str = Form(...),
    implementation_type: str = Form(...),
    test_frequency: str = Form(...),
    criticality: str = Form(...),
    owner_role: str = Form(""),
    objective: str = Form(""),
    procedure: str = Form(""),
    operation_frequency: str = Form(""),
    owner_user_id: str = Form(""),
    default_test_procedure: str = Form(""),
    evidence_instructions: str = Form(""),
    is_active: str = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    ctrl = svc.update_control(
        db, control_id, control_ref=control_ref.strip(), title=title.strip(),
        description=description.strip(), domain=domain, control_type=control_type,
        implementation_type=implementation_type, test_frequency=test_frequency,
        criticality=criticality, owner_role=owner_role.strip() or None,
        objective=objective.strip() or None,
        procedure=procedure.strip() or None,
        operation_frequency=operation_frequency.strip() or None,
        owner_user_id=int(owner_user_id) if owner_user_id.strip() else None,
        default_test_procedure=default_test_procedure.strip() or None,
        evidence_instructions=evidence_instructions.strip() or None,
        is_active=is_active == "on",
    )
    if not ctrl:
        raise HTTPException(status_code=404, detail="Control not found")

    form = await request.form()
    _save_mappings(db, control_id, form)

    log_audit(db, AUDIT_ACTION_UPDATE, AUDIT_ENTITY_CONTROL,
              entity_id=ctrl.id, entity_label=ctrl.control_ref,
              description=f"Updated control {ctrl.control_ref}",
              actor_user=current_user)
    db.commit()

    return RedirectResponse(url=f"/controls/{control_id}?message={quote('Control updated')}&message_type=success", status_code=303)


@router.post("/controls/{control_id}/delete", response_class=HTMLResponse)
async def control_delete(control_id: int, db: Session = Depends(get_db), current_user: User = Depends(_analyst_dep)):
    ctrl = db.query(Control).filter(Control.id == control_id).first()
    if not ctrl:
        raise HTTPException(status_code=404, detail="Control not found")

    ref = ctrl.control_ref
    log_audit(db, AUDIT_ACTION_DELETE, AUDIT_ENTITY_CONTROL,
              entity_id=ctrl.id, entity_label=ref,
              description=f"Deleted control {ref}",
              actor_user=current_user)
    svc.delete_control(db, control_id)
    db.commit()

    return RedirectResponse(url=f"/controls?message={quote('Control deleted')}&message_type=success", status_code=303)


# ==================== ORG-LEVEL IMPLEMENTATIONS ====================

@router.post("/controls/{control_id}/implement", response_class=HTMLResponse)
async def control_implement(
    control_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    """Create an org-level implementation for this control."""
    ctrl = db.query(Control).filter(Control.id == control_id).first()
    if not ctrl:
        raise HTTPException(status_code=404, detail="Control not found")

    # Check if org-level impl already exists
    existing = db.query(ControlImplementation).filter(
        ControlImplementation.control_id == control_id,
        ControlImplementation.vendor_id == None,
    ).first()
    if existing:
        return RedirectResponse(
            url=f"/controls/{control_id}?message={quote('Org implementation already exists')}&message_type=warning",
            status_code=303,
        )

    impl = svc.create_implementation(db, control_id)
    log_audit(db, AUDIT_ACTION_CREATE, AUDIT_ENTITY_CONTROL_IMPL,
              entity_id=impl.id, entity_label=ctrl.control_ref,
              description=f"Created org-level implementation for {ctrl.control_ref}",
              actor_user=current_user)
    db.commit()

    return RedirectResponse(
        url=f"/controls/{control_id}?message={quote('Implementation created')}&message_type=success",
        status_code=303,
    )


@router.post("/controls/bulk-implement", response_class=HTMLResponse)
async def control_bulk_implement(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    """Bulk-create org-level implementations for selected controls."""
    form = await request.form()
    control_ids = [int(v) for k, v in form.multi_items() if k == "control_ids"]

    if control_ids:
        count = svc.bulk_create_org_implementations(db, control_ids)
        log_audit(db, AUDIT_ACTION_CREATE, AUDIT_ENTITY_CONTROL_IMPL,
                  entity_label="Bulk org implementations",
                  description=f"Bulk-created {count} org-level implementations",
                  actor_user=current_user)
        db.commit()
        msg = quote(f"Created {count} implementations")
    else:
        msg = quote("No controls selected")

    return RedirectResponse(url=f"/controls?message={msg}&message_type=success", status_code=303)


# ==================== VENDOR IMPLEMENTATIONS ====================

@router.get("/vendors/{vendor_id}/controls", response_class=HTMLResponse)
async def vendor_controls(
    request: Request,
    vendor_id: int,
    domain: str = "",
    status: str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    vendor = db.query(Vendor).filter(Vendor.id == vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    impls = svc.get_vendor_implementations(db, vendor_id)

    if domain:
        impls = [i for i in impls if i.control.domain == domain]
    if status:
        impls = [i for i in impls if i.status == status]

    stats = svc.get_vendor_control_stats(db, vendor_id)

    all_controls = svc.get_all_controls(db, active_only=True)
    existing_control_ids = {i.control_id for i in db.query(ControlImplementation).filter(
        ControlImplementation.vendor_id == vendor_id
    ).all()}
    available_controls = [c for c in all_controls if c.id not in existing_control_ids]

    return templates.TemplateResponse("vendor_controls.html", {
        "request": request,
        "vendor": vendor,
        "implementations": impls,
        "stats": stats,
        "available_controls": available_controls,
        "domains": VALID_CONTROL_DOMAINS,
        "impl_statuses": VALID_IMPL_STATUSES,
        "impl_status_labels": IMPL_STATUS_LABELS,
        "impl_status_colors": IMPL_STATUS_COLORS,
        "effectiveness_labels": EFFECTIVENESS_LABELS,
        "effectiveness_colors": EFFECTIVENESS_COLORS,
        "frequency_labels": CONTROL_FREQUENCY_LABELS,
        "f_domain": domain,
        "f_status": status,
    })


@router.post("/vendors/{vendor_id}/controls/bulk", response_class=HTMLResponse)
async def vendor_controls_bulk(
    request: Request,
    vendor_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    vendor = db.query(Vendor).filter(Vendor.id == vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    form = await request.form()
    control_ids = [int(v) for k, v in form.multi_items() if k == "control_ids"]

    if control_ids:
        count = svc.bulk_create_implementations(db, vendor_id, control_ids)
        log_audit(db, AUDIT_ACTION_CREATE, AUDIT_ENTITY_CONTROL_IMPL,
                  entity_label=vendor.name,
                  description=f"Bulk-added {count} control implementations for {vendor.name}",
                  actor_user=current_user)
        db.commit()
        msg = quote(f"Added {count} controls")
    else:
        msg = quote("No controls selected")

    return RedirectResponse(url=f"/vendors/{vendor_id}/controls?message={msg}&message_type=success", status_code=303)


@router.get("/controls/implementations/{impl_id}", response_class=HTMLResponse)
async def control_impl_detail(
    request: Request, impl_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_login),
):
    impl = svc.get_implementation(db, impl_id)
    if not impl:
        raise HTTPException(status_code=404, detail="Implementation not found")

    users = db.query(User).filter(User.is_active == True).order_by(User.display_name).all()

    # Health score
    health = compute_health_score(db, impl)
    readiness = compute_readiness(db, impl)

    # Attestation (Feature 6)
    attestations = att_svc.get_implementation_attestations(db, impl_id)
    latest_attestation = attestations[0] if attestations else None

    # Implementation-level evidence (Feature 7)
    impl_evidence = svc.get_implementation_evidence(db, impl_id)

    # Health trend (Feature 11)
    health_trend = get_health_trend(db, impl_id)

    return templates.TemplateResponse("control_impl_detail.html", {
        "request": request,
        "impl": impl,
        "users": users,
        "health": health,
        "readiness": readiness,
        "attestations": attestations,
        "latest_attestation": latest_attestation,
        "attestation_status_labels": ATTESTATION_STATUS_LABELS,
        "attestation_status_colors": ATTESTATION_STATUS_COLORS,
        "impl_evidence": impl_evidence,
        "health_trend": health_trend,
        "impl_statuses": VALID_IMPL_STATUSES,
        "impl_status_labels": IMPL_STATUS_LABELS,
        "impl_status_colors": IMPL_STATUS_COLORS,
        "effectiveness_levels": VALID_EFFECTIVENESS_LEVELS,
        "effectiveness_labels": EFFECTIVENESS_LABELS,
        "effectiveness_colors": EFFECTIVENESS_COLORS,
        "control_type_labels": CONTROL_TYPE_LABELS,
        "frequency_labels": CONTROL_FREQUENCY_LABELS,
        "impl_type_labels": CONTROL_IMPL_TYPE_LABELS,
        "test_types": VALID_TEST_TYPES,
        "test_type_labels": TEST_TYPE_LABELS,
        "test_results": VALID_TEST_RESULTS,
        "test_result_labels": TEST_RESULT_LABELS,
        "test_result_colors": TEST_RESULT_COLORS,
        "framework_display": FRAMEWORK_DISPLAY,
    })


@router.post("/controls/implementations/{impl_id}", response_class=HTMLResponse)
async def control_impl_update(
    request: Request,
    impl_id: int,
    status: str = Form(...),
    effectiveness: str = Form(...),
    owner_user_id: str = Form(""),
    notes: str = Form(""),
    implemented_date: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    impl = svc.get_implementation(db, impl_id)
    if not impl:
        raise HTTPException(status_code=404, detail="Implementation not found")

    old_status = impl.status
    kwargs = {"status": status, "effectiveness": effectiveness, "notes": notes.strip()}
    if owner_user_id.strip():
        kwargs["owner_user_id"] = int(owner_user_id)
    else:
        kwargs["owner_user_id"] = None
    if implemented_date.strip():
        kwargs["implemented_date"] = datetime.strptime(implemented_date.strip(), "%Y-%m-%d")
    else:
        kwargs["implemented_date"] = None

    svc.update_implementation(db, impl_id, **kwargs)

    log_audit(db, AUDIT_ACTION_UPDATE, AUDIT_ENTITY_CONTROL_IMPL,
              entity_id=impl_id,
              entity_label=f"{impl.control.control_ref} — {impl.vendor.name if impl.vendor else 'Org'}",
              old_value=old_status, new_value=status,
              description=f"Updated control implementation status: {old_status} → {status}",
              actor_user=current_user)

    if impl.vendor_id:
        from models import VendorActivity, ACTIVITY_CONTROL_IMPL_UPDATED
        db.add(VendorActivity(
            vendor_id=impl.vendor_id,
            activity_type=ACTIVITY_CONTROL_IMPL_UPDATED,
            description=f"Control {impl.control.control_ref} updated: {old_status} → {status}",
            user_id=current_user.id,
        ))

    db.commit()

    vendor_id = impl.vendor_id
    return RedirectResponse(
        url=f"/controls/implementations/{impl_id}?message={quote('Implementation updated')}&message_type=success",
        status_code=303,
    )


@router.post("/controls/implementations/{impl_id}/delete", response_class=HTMLResponse)
async def control_impl_delete(impl_id: int, db: Session = Depends(get_db), current_user: User = Depends(_analyst_dep)):
    impl = svc.get_implementation(db, impl_id)
    if not impl:
        raise HTTPException(status_code=404, detail="Implementation not found")

    vendor_id = impl.vendor_id
    log_audit(db, AUDIT_ACTION_DELETE, AUDIT_ENTITY_CONTROL_IMPL,
              entity_id=impl_id, description=f"Deleted control implementation",
              actor_user=current_user)
    svc.delete_implementation(db, impl_id)
    db.commit()

    if vendor_id:
        return RedirectResponse(url=f"/vendors/{vendor_id}/controls?message={quote('Implementation deleted')}&message_type=success", status_code=303)
    return RedirectResponse(url="/controls?message={}&message_type=success".format(quote("Implementation deleted")), status_code=303)


# ==================== CONTROL TESTING ====================

@router.post("/controls/implementations/{impl_id}/tests", response_class=HTMLResponse)
async def control_test_create(
    impl_id: int,
    test_type: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    """Create a new ad-hoc test in IN_PROGRESS status and redirect to its workspace."""
    impl = svc.get_implementation(db, impl_id)
    if not impl:
        raise HTTPException(status_code=404, detail="Implementation not found")

    test = svc.create_test(db, impl_id, test_type, current_user.id)

    # Pre-fill from control templates (Feature 4)
    prefill = {}
    if impl.control.default_test_procedure:
        prefill["test_procedure"] = impl.control.default_test_procedure
    if prefill:
        svc.save_test_progress(db, test.id, **prefill)

    log_audit(db, AUDIT_ACTION_CREATE, "control_test",
              entity_id=test.id,
              entity_label=f"Test for {impl.control.control_ref}",
              description=f"Started new {test_type} test",
              actor_user=current_user)
    db.commit()

    return RedirectResponse(
        url=f"/controls/tests/{test.id}?message={quote('Test created — fill in details and save your progress')}&message_type=success",
        status_code=303,
    )


@router.get("/controls/tests/{test_id}", response_class=HTMLResponse)
async def control_test_detail(request: Request, test_id: int, db: Session = Depends(get_db), current_user: User = Depends(_analyst_dep)):
    test = svc.get_test(db, test_id)
    if not test:
        raise HTTPException(status_code=404, detail="Test not found")

    users = db.query(User).filter(User.is_active == True).order_by(User.display_name).all()

    # Findings for this test
    test_findings = svc.get_test_findings(db, test_id)

    # SoD checks
    sod_tester_is_owner = (
        test.tester_user_id and test.implementation.control.owner_user_id
        and test.tester_user_id == test.implementation.control.owner_user_id
    )
    sod_reviewer_is_tester = (
        test.reviewer_user_id and test.tester_user_id
        and test.reviewer_user_id == test.tester_user_id
    )

    # Next test navigation (#11) — find next overdue/upcoming org-level impl
    next_impl = None
    if test.status == TEST_STATUS_COMPLETED:
        from sqlalchemy.orm import joinedload as jl
        next_impl = db.query(ControlImplementation).options(
            jl(ControlImplementation.control),
        ).filter(
            ControlImplementation.vendor_id == None,
            ControlImplementation.status == IMPL_STATUS_IMPLEMENTED,
            ControlImplementation.next_test_date != None,
            ControlImplementation.id != test.implementation_id,
        ).order_by(
            ControlImplementation.next_test_date.asc(),
        ).first()

    return templates.TemplateResponse("control_test_detail.html", {
        "request": request,
        "test": test,
        "current_user": current_user,
        "users": users,
        "test_findings": test_findings,
        "next_impl": next_impl,
        "sod_tester_is_owner": sod_tester_is_owner,
        "sod_reviewer_is_tester": sod_reviewer_is_tester,
        "test_types": VALID_TEST_TYPES,
        "test_type_labels": TEST_TYPE_LABELS,
        "test_results": VALID_TEST_RESULTS,
        "test_result_labels": TEST_RESULT_LABELS,
        "test_result_colors": TEST_RESULT_COLORS,
        "finding_risk_ratings": VALID_FINDING_RISK_RATINGS,
        "finding_risk_labels": FINDING_RISK_LABELS,
        "finding_risk_colors": FINDING_RISK_COLORS,
        "finding_types": VALID_FINDING_TYPES,
        "finding_type_labels": FINDING_TYPE_LABELS,
        "finding_statuses": VALID_FINDING_STATUSES,
        "finding_status_labels": FINDING_STATUS_LABELS,
        "finding_status_colors": FINDING_STATUS_COLORS,
        "severities": VALID_SEVERITIES,
        "test_status_labels": TEST_STATUS_LABELS,
        "test_status_colors": TEST_STATUS_COLORS,
        "framework_display": FRAMEWORK_DISPLAY,
        "TEST_STATUS_IN_PROGRESS": TEST_STATUS_IN_PROGRESS,
        "TEST_STATUS_COMPLETED": TEST_STATUS_COMPLETED,
    })


@router.post("/controls/tests/{test_id}/review", response_class=HTMLResponse)
async def control_test_review(
    request: Request,
    test_id: int,
    review_notes: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    test = svc.get_test(db, test_id)
    if not test:
        raise HTTPException(status_code=404, detail="Test not found")

    svc.submit_test_review(db, test_id, current_user.id, review_notes.strip())

    # SoD note in audit if reviewer == tester
    sod_note = ""
    if test.tester_user_id and test.tester_user_id == current_user.id:
        sod_note = " (SoD note: reviewer is same as tester)"

    log_audit(db, AUDIT_ACTION_UPDATE, "control_test",
              entity_id=test.id,
              entity_label=f"Reviewed test for {test.implementation.control.control_ref}",
              description=f"Reviewer sign-off by {current_user.display_name}{sod_note}",
              actor_user=current_user)
    db.commit()

    return RedirectResponse(
        url=f"/controls/tests/{test_id}?message={quote('Review sign-off recorded')}&message_type=success",
        status_code=303,
    )


@router.get("/controls/tests/{test_id}/export.pdf")
async def control_test_export_pdf(
    test_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    test = svc.get_test(db, test_id)
    if not test:
        raise HTTPException(status_code=404, detail="Test not found")

    context = {
        "test": test,
        "control": test.implementation.control,
        "impl": test.implementation,
        "test_type_labels": TEST_TYPE_LABELS,
        "test_result_labels": TEST_RESULT_LABELS,
        "test_result_colors": TEST_RESULT_COLORS,
        "finding_risk_labels": FINDING_RISK_LABELS,
        "finding_risk_colors": FINDING_RISK_COLORS,
        "framework_display": FRAMEWORK_DISPLAY,
        "generated_at": datetime.utcnow(),
    }

    pdf_bytes = generate_control_test_pdf(context)
    ctrl_ref = test.implementation.control.control_ref.replace(" ", "_")
    filename = f"Workpaper_{ctrl_ref}_Test_{test.id}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/controls/tests/{test_id}/evidence", response_class=HTMLResponse)
async def control_test_upload_evidence(
    request: Request, test_id: int,
    db: Session = Depends(get_db), current_user: User = Depends(_analyst_dep),
):
    test = svc.get_test(db, test_id)
    if not test:
        raise HTTPException(status_code=404, detail="Test not found")

    form = await request.form()
    files = form.getlist("evidence_files")
    count = 0
    for f in files:
        if hasattr(f, 'filename') and f.filename:
            ev = await svc.store_control_evidence(f, test_id)
            db.add(ev)
            count += 1
    db.commit()

    return RedirectResponse(
        url=f"/controls/tests/{test_id}?message={quote(f'Uploaded {count} file(s)')}&message_type=success",
        status_code=303,
    )


@router.get("/controls/evidence/{evidence_id}/download")
async def control_evidence_download(evidence_id: int, db: Session = Depends(get_db), current_user: User = Depends(_analyst_dep)):
    ev = svc.get_evidence(db, evidence_id)
    if not ev:
        raise HTTPException(status_code=404, detail="Evidence not found")
    import os
    if not os.path.exists(ev.stored_path):
        raise HTTPException(status_code=404, detail="File not found on disk")
    return FileResponse(ev.stored_path, filename=ev.original_filename, media_type=ev.content_type or "application/octet-stream")


@router.post("/controls/evidence/{evidence_id}/delete", response_class=HTMLResponse)
async def control_evidence_delete(evidence_id: int, db: Session = Depends(get_db), current_user: User = Depends(_analyst_dep)):
    ev = svc.get_evidence(db, evidence_id)
    if not ev:
        raise HTTPException(status_code=404, detail="Evidence not found")
    test_id = ev.test_id
    svc.delete_evidence(db, evidence_id)
    db.commit()
    return RedirectResponse(
        url=f"/controls/tests/{test_id}?message={quote('Evidence deleted')}&message_type=success",
        status_code=303,
    )


# ==================== FINDINGS ====================

@router.post("/controls/tests/{test_id}/findings", response_class=HTMLResponse)
async def control_test_add_finding(
    request: Request,
    test_id: int,
    finding_type: str = Form("OPERATING_DEFICIENCY"),
    severity: str = Form("MEDIUM"),
    criteria: str = Form(""),
    condition: str = Form(""),
    cause: str = Form(""),
    effect: str = Form(""),
    recommendation: str = Form(""),
    owner_user_id: str = Form(""),
    due_date: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    test = svc.get_test(db, test_id)
    if not test:
        raise HTTPException(status_code=404, detail="Test not found")

    dd = datetime.strptime(due_date.strip(), "%Y-%m-%d") if due_date.strip() else None
    oid = int(owner_user_id) if owner_user_id.strip() else None

    finding = svc.create_finding(
        db, test_id, finding_type, severity,
        criteria=criteria.strip() or None,
        condition=condition.strip() or None,
        cause=cause.strip() or None,
        effect=effect.strip() or None,
        recommendation=recommendation.strip() or None,
        owner_user_id=oid, due_date=dd,
    )

    log_audit(db, AUDIT_ACTION_CREATE, "control_finding",
              entity_id=finding.id,
              entity_label=f"Finding for {test.implementation.control.control_ref}",
              description=f"Created {finding_type} finding: {severity}",
              actor_user=current_user)
    db.commit()

    return RedirectResponse(
        url=f"/controls/tests/{test_id}?message={quote('Finding added')}&message_type=success#findings",
        status_code=303,
    )


@router.post("/controls/findings/{finding_id}/update", response_class=HTMLResponse)
async def control_finding_update(
    finding_id: int,
    status: str = Form(""),
    severity: str = Form(""),
    owner_user_id: str = Form(""),
    due_date: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    finding = svc.get_finding(db, finding_id)
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")

    kwargs = {}
    if status.strip():
        kwargs["status"] = status.strip()
    if severity.strip():
        kwargs["severity"] = severity.strip()
    if owner_user_id.strip():
        kwargs["owner_user_id"] = int(owner_user_id)
    elif owner_user_id == "":
        kwargs["owner_user_id"] = None
    if due_date.strip():
        kwargs["due_date"] = datetime.strptime(due_date.strip(), "%Y-%m-%d")

    svc.update_finding(db, finding_id, **kwargs)

    log_audit(db, AUDIT_ACTION_UPDATE, "control_finding",
              entity_id=finding_id,
              description=f"Updated finding: {kwargs}",
              actor_user=current_user)
    db.commit()

    test_id = finding.control_test_id
    return RedirectResponse(
        url=f"/controls/tests/{test_id}?message={quote('Finding updated')}&message_type=success#findings",
        status_code=303,
    )


@router.post("/controls/findings/{finding_id}/close", response_class=HTMLResponse)
async def control_finding_close(
    finding_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    finding = svc.get_finding(db, finding_id)
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")

    svc.close_finding(db, finding_id)

    log_audit(db, AUDIT_ACTION_UPDATE, "control_finding",
              entity_id=finding_id,
              description=f"Closed finding",
              actor_user=current_user)
    db.commit()

    test_id = finding.control_test_id
    return RedirectResponse(
        url=f"/controls/tests/{test_id}?message={quote('Finding closed')}&message_type=success#findings",
        status_code=303,
    )


# ==================== ROLL-FORWARD ====================

@router.post("/controls/tests/{test_id}/roll-forward", response_class=HTMLResponse)
async def control_test_roll_forward(
    test_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    """Clone a completed test as a roll-forward for the next testing period."""
    source = svc.get_test(db, test_id)
    if not source or source.status != TEST_STATUS_COMPLETED:
        raise HTTPException(status_code=404, detail="Completed test not found")

    new_test = svc.roll_forward_test(db, test_id, current_user.id)

    log_audit(db, AUDIT_ACTION_CREATE, "control_test",
              entity_id=new_test.id,
              entity_label=f"Roll-forward test for {source.implementation.control.control_ref}",
              description=f"Rolled forward from test #{test_id}",
              actor_user=current_user)
    db.commit()

    return RedirectResponse(
        url=f"/controls/tests/{new_test.id}?message={quote('Roll-forward test created from previous workpaper')}&message_type=success",
        status_code=303,
    )


# ==================== ATTESTATIONS (Feature 6) ====================

@router.post("/controls/implementations/{impl_id}/attestations", response_class=HTMLResponse)
async def control_attestation_request(
    impl_id: int,
    attestor_user_id: str = Form(""),
    due_date: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    """Request an attestation from a control owner."""
    impl = svc.get_implementation(db, impl_id)
    if not impl:
        raise HTTPException(status_code=404, detail="Implementation not found")

    att_user_id = int(attestor_user_id) if attestor_user_id.strip() else (impl.owner_user_id or current_user.id)
    dd = datetime.strptime(due_date.strip(), "%Y-%m-%d") if due_date.strip() else None

    att = att_svc.request_attestation(db, impl_id, att_user_id, dd)

    log_audit(db, AUDIT_ACTION_CREATE, "control_attestation",
              entity_id=att.id,
              entity_label=f"Attestation for {impl.control.control_ref}",
              description=f"Requested attestation from user {att_user_id}",
              actor_user=current_user)
    db.commit()

    return RedirectResponse(
        url=f"/controls/implementations/{impl_id}?message={quote('Attestation requested')}&message_type=success",
        status_code=303,
    )


@router.post("/controls/attestations/{attestation_id}/submit", response_class=HTMLResponse)
async def control_attestation_submit(
    attestation_id: int,
    is_effective: str = Form(""),
    notes: str = Form(""),
    evidence_notes: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_login),
):
    """Submit an attestation response."""
    att = att_svc.get_attestation(db, attestation_id)
    if not att:
        raise HTTPException(status_code=404, detail="Attestation not found")

    effective = is_effective.lower() in ("true", "yes", "1", "on")
    att_svc.submit_attestation(db, attestation_id, effective, notes.strip(), evidence_notes.strip())

    log_audit(db, AUDIT_ACTION_UPDATE, "control_attestation",
              entity_id=attestation_id,
              entity_label=f"Attestation for {att.implementation.control.control_ref}",
              description=f"Attestation submitted: {'Effective' if effective else 'Not Effective'}",
              actor_user=current_user)
    db.commit()

    return RedirectResponse(
        url=f"/controls/implementations/{att.implementation_id}?message={quote('Attestation submitted')}&message_type=success",
        status_code=303,
    )


@router.post("/controls/attestations/{attestation_id}/reject", response_class=HTMLResponse)
async def control_attestation_reject(
    attestation_id: int,
    notes: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_login),
):
    """Reject/decline an attestation."""
    att = att_svc.get_attestation(db, attestation_id)
    if not att:
        raise HTTPException(status_code=404, detail="Attestation not found")

    att_svc.reject_attestation(db, attestation_id, notes.strip())

    log_audit(db, AUDIT_ACTION_UPDATE, "control_attestation",
              entity_id=attestation_id,
              entity_label=f"Attestation for {att.implementation.control.control_ref}",
              description=f"Attestation rejected",
              actor_user=current_user)
    db.commit()

    return RedirectResponse(
        url=f"/controls/implementations/{att.implementation_id}?message={quote('Attestation declined')}&message_type=warning",
        status_code=303,
    )


# ==================== IMPLEMENTATION EVIDENCE (Feature 7) ====================

@router.post("/controls/implementations/{impl_id}/evidence", response_class=HTMLResponse)
async def control_impl_upload_evidence(
    request: Request,
    impl_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    """Upload evidence directly to an implementation (not tied to a test)."""
    impl = svc.get_implementation(db, impl_id)
    if not impl:
        raise HTTPException(status_code=404, detail="Implementation not found")

    form = await request.form()
    files = form.getlist("evidence_files")
    count = 0
    for f in files:
        if hasattr(f, 'filename') and f.filename:
            ev = await svc.store_implementation_evidence(f, impl_id)
            ev.implementation_id = impl_id
            db.add(ev)
            count += 1
    db.commit()

    return RedirectResponse(
        url=f"/controls/implementations/{impl_id}?message={quote(f'Uploaded {count} evidence file(s)')}&message_type=success",
        status_code=303,
    )


# ==================== HEALTH SNAPSHOTS (Feature 11) ====================

@router.post("/controls/record-health-snapshots", response_class=HTMLResponse)
async def control_record_health_snapshots(
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    """Record health snapshots for all org-level implementations (manual trigger)."""
    count = record_all_health_snapshots(db)
    db.commit()
    return RedirectResponse(
        url=f"/controls/dashboard?message={quote(f'Recorded {count} health snapshots')}&message_type=success",
        status_code=303,
    )


# ==================== API ENDPOINTS (Features 9, 11) ====================

@router.get("/api/controls/test-timeline")
async def api_test_timeline(
    months: int = 12,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_login),
):
    """JSON API: monthly test results for Chart.js."""
    data = svc.get_test_results_timeline(db, months)
    return data


@router.get("/api/controls/health-trend")
async def api_health_trend(
    impl_id: int = 0,
    months: int = 12,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_login),
):
    """JSON API: health score trend for Chart.js."""
    if impl_id:
        return get_health_trend(db, impl_id, months)
    else:
        return get_portfolio_health_trend(db, months)


# ==================== GAP ANALYSIS (per-vendor) ====================

@router.get("/vendors/{vendor_id}/controls/gaps", response_class=HTMLResponse)
async def vendor_gap_analysis(
    request: Request,
    vendor_id: int,
    framework: str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    vendor = db.query(Vendor).filter(Vendor.id == vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    gaps = dash_svc.get_vendor_gap_analysis(db, vendor_id, framework or None)

    total = len(gaps)
    gap_count = sum(1 for g in gaps if g["is_gap"])
    impl_count = total - gap_count

    return templates.TemplateResponse("vendor_gap_analysis.html", {
        "request": request,
        "vendor": vendor,
        "gaps": gaps,
        "total": total,
        "gap_count": gap_count,
        "impl_count": impl_count,
        "frameworks": AVAILABLE_FRAMEWORKS,
        "framework_display": FRAMEWORK_DISPLAY,
        "f_framework": framework,
        "impl_status_labels": IMPL_STATUS_LABELS,
        "impl_status_colors": IMPL_STATUS_COLORS,
        "effectiveness_labels": EFFECTIVENESS_LABELS,
        "effectiveness_colors": EFFECTIVENESS_COLORS,
    })


# ==================== HELPERS ====================

def _form_context(db: Session, control=None, error=None):
    """Build common context for control create/edit form."""
    qb_items = db.query(QuestionBankItem).filter(
        QuestionBankItem.is_active == True
    ).order_by(QuestionBankItem.category, QuestionBankItem.id).all()

    risk_stmts = db.query(RiskStatement).filter(
        RiskStatement.is_active == True
    ).order_by(RiskStatement.category, RiskStatement.id).all()

    # Group question bank items by category
    qb_grouped = {}
    for item in qb_items:
        qb_grouped.setdefault(item.category, []).append(item)

    # Group risk statements by category
    rs_grouped = {}
    for rs in risk_stmts:
        rs_grouped.setdefault(rs.category, []).append(rs)

    # Get existing mappings if editing
    mapped_question_ids = set()
    mapped_risk_ids = set()
    existing_fw_refs = {}
    if control:
        mapped_question_ids = {m.question_bank_item_id for m in control.question_mappings}
        mapped_risk_ids = {m.risk_statement_id for m in control.risk_mappings}
        for m in control.framework_mappings:
            existing_fw_refs[m.framework] = m.reference

    users = db.query(User).filter(User.is_active == True).order_by(User.display_name).all()

    return {
        "control": control,
        "domains": VALID_CONTROL_DOMAINS,
        "control_types": VALID_CONTROL_TYPES,
        "control_type_labels": CONTROL_TYPE_LABELS,
        "impl_types": VALID_CONTROL_IMPL_TYPES,
        "impl_type_labels": CONTROL_IMPL_TYPE_LABELS,
        "frequencies": VALID_CONTROL_FREQUENCIES,
        "frequency_labels": CONTROL_FREQUENCY_LABELS,
        "criticalities": VALID_CONTROL_CRITICALITIES,
        "operation_frequencies": VALID_CONTROL_FREQUENCIES,
        "frameworks": AVAILABLE_FRAMEWORKS,
        "framework_display": FRAMEWORK_DISPLAY,
        "users": users,
        "qb_grouped": qb_grouped,
        "rs_grouped": rs_grouped,
        "mapped_question_ids": mapped_question_ids,
        "mapped_risk_ids": mapped_risk_ids,
        "existing_fw_refs": existing_fw_refs,
        "error": error,
    }


def _save_mappings(db: Session, control_id: int, form):
    """Parse framework, question, and risk mappings from form data."""
    # Framework mappings: checkbox pattern — fw_{KEY}_enabled + fw_{KEY}_ref
    fw_mappings = []
    for key, _label in AVAILABLE_FRAMEWORKS:
        enabled = form.get(f"fw_{key}_enabled")
        ref = form.get(f"fw_{key}_ref", "").strip()
        if enabled and ref:
            fw_mappings.append((key, ref))
    svc.set_framework_mappings(db, control_id, fw_mappings)

    # Question mappings
    q_ids = [int(v) for k, v in form.multi_items() if k == "question_ids"]
    svc.set_question_mappings(db, control_id, q_ids)

    # Risk mappings
    r_ids = [int(v) for k, v in form.multi_items() if k == "risk_ids"]
    svc.set_risk_mappings(db, control_id, r_ids)


def _parse_enhanced_test_fields(
    test_period_start: str, test_period_end: str,
    sample_size: str, population_size: str,
    exceptions_count: str, exception_details: str,
    conclusion: str, finding_risk_rating: str,
) -> dict:
    """Parse enhanced test workpaper fields from form strings into typed values."""
    result = {}
    if test_period_start.strip():
        result["test_period_start"] = datetime.strptime(test_period_start.strip(), "%Y-%m-%d")
    if test_period_end.strip():
        result["test_period_end"] = datetime.strptime(test_period_end.strip(), "%Y-%m-%d")
    if sample_size.strip():
        result["sample_size"] = int(sample_size)
    if population_size.strip():
        result["population_size"] = int(population_size)
    if exceptions_count.strip():
        result["exceptions_count"] = int(exceptions_count)
    if exception_details.strip():
        result["exception_details"] = exception_details.strip()
    if conclusion.strip():
        result["conclusion"] = conclusion.strip()
    if finding_risk_rating.strip():
        result["finding_risk_rating"] = finding_risk_rating.strip()
    return result


@router.get("/controls/frameworks/{framework_key}/edit", response_class=HTMLResponse)
async def framework_edit_form(
    request: Request,
    framework_key: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    from app.services import framework_service as fw_svc
    fw = fw_svc.get_custom_framework_by_key(db, framework_key)
    if not fw:
        raise HTTPException(status_code=404, detail="Custom framework not found")
    return templates.TemplateResponse("framework_form.html", {
        "request": request,
        "framework": fw,
    })


@router.post("/controls/frameworks/{framework_key}/edit", response_class=HTMLResponse)
async def framework_edit(
    request: Request,
    framework_key: str,
    display_name: str = Form(...),
    description: str = Form(None),
    version: str = Form(None),
    source_url: str = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    from app.services import framework_service as fw_svc
    from models import AUDIT_ACTION_UPDATE, AUDIT_ENTITY_CUSTOM_FRAMEWORK
    fw = fw_svc.get_custom_framework_by_key(db, framework_key)
    if not fw:
        raise HTTPException(status_code=404, detail="Custom framework not found")
    fw_svc.update_custom_framework(db, fw.id,
        display_name=display_name, description=description,
        version=version, source_url=source_url,
    )
    log_audit(db, action=AUDIT_ACTION_UPDATE, entity_type=AUDIT_ENTITY_CUSTOM_FRAMEWORK,
              entity_id=fw.id, entity_label=fw.framework_key,
              actor_user=current_user)
    db.commit()
    return RedirectResponse(url=f"/controls/frameworks/{framework_key}", status_code=303)


@router.post("/controls/frameworks/{framework_key}/delete", response_class=HTMLResponse)
async def framework_delete(
    request: Request,
    framework_key: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    from app.services import framework_service as fw_svc
    from models import AUDIT_ACTION_DELETE, AUDIT_ENTITY_CUSTOM_FRAMEWORK
    fw = fw_svc.get_custom_framework_by_key(db, framework_key)
    if fw:
        log_audit(db, action=AUDIT_ACTION_DELETE, entity_type=AUDIT_ENTITY_CUSTOM_FRAMEWORK,
                  entity_id=fw.id, entity_label=fw.framework_key,
                  actor_user=current_user)
        fw_svc.delete_custom_framework(db, framework_key)
        db.commit()
    return RedirectResponse(url="/controls/frameworks", status_code=303)


@router.get("/controls/frameworks/{framework_key}/requirements/new", response_class=HTMLResponse)
async def framework_requirement_add_form(
    request: Request,
    framework_key: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    from app.services import framework_service as fw_svc
    fw_display = fw_svc.get_framework_display_dynamic(db)
    fw_label = fw_display.get(framework_key, framework_key)
    return templates.TemplateResponse("framework_requirement_add.html", {
        "request": request,
        "framework_key": framework_key,
        "fw_label": fw_label,
    })


@router.post("/controls/frameworks/{framework_key}/requirements/new", response_class=HTMLResponse)
async def framework_requirement_add(
    request: Request,
    framework_key: str,
    reference: str = Form(...),
    title: str = Form(...),
    description: str = Form(None),
    category: str = Form(None),
    subcategory: str = Form(None),
    guidance: str = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    from app.services import framework_service as fw_svc
    fw_svc.create_requirement(
        db, framework_key, reference, title,
        description=description, category=category,
        subcategory=subcategory, guidance=guidance,
    )
    db.commit()
    return RedirectResponse(url=f"/controls/frameworks/{framework_key}", status_code=303)


@router.post("/controls/frameworks/{framework_key}/requirements/import", response_class=HTMLResponse)
async def framework_requirements_import(
    request: Request,
    framework_key: str,
    csv_file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    from app.services import framework_service as fw_svc
    content = (await csv_file.read()).decode("utf-8-sig")
    result = fw_svc.import_requirements_csv(db, framework_key, content)
    db.commit()
    return RedirectResponse(url=f"/controls/frameworks/{framework_key}", status_code=303)


@router.get("/controls/frameworks/{framework_key}/requirements/export")
async def framework_requirements_export(
    request: Request,
    framework_key: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    from app.services import framework_service as fw_svc
    csv_content = fw_svc.export_requirements_csv(db, framework_key)
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={framework_key}_requirements.csv"},
    )


# ==================== COMPLIANCE POSTURE DASHBOARD ====================

@router.get("/compliance/posture", response_class=HTMLResponse)
async def compliance_posture(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_login),
):
    from app.services.compliance_posture_service import get_compliance_posture
    data = get_compliance_posture(db)
    return templates.TemplateResponse("compliance_posture.html", {
        "request": request,
        "postures": data["postures"],
        "overall_pct": data["overall_pct"],
        "total_gaps": data["total_gaps"],
        "frameworks_tracked": data["frameworks_tracked"],
        "frameworks_above_80": data["frameworks_above_80"],
    })
