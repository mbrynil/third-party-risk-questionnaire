"""Controls module — library, implementations, testing, dashboard, gap analysis."""

from fastapi import APIRouter, Request, Form, Depends, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from sqlalchemy.orm import Session
from urllib.parse import quote
from datetime import datetime

from app import templates
from models import (
    get_db, User, Vendor, Control, ControlImplementation, QuestionBankItem, RiskStatement,
    AVAILABLE_FRAMEWORKS, FRAMEWORK_DISPLAY, VALID_CONTROL_DOMAINS,
    VALID_CONTROL_TYPES, CONTROL_TYPE_LABELS,
    VALID_CONTROL_IMPL_TYPES, CONTROL_IMPL_TYPE_LABELS,
    VALID_CONTROL_FREQUENCIES, CONTROL_FREQUENCY_LABELS,
    VALID_CONTROL_CRITICALITIES,
    VALID_IMPL_STATUSES, IMPL_STATUS_LABELS, IMPL_STATUS_COLORS,
    VALID_EFFECTIVENESS_LEVELS, EFFECTIVENESS_LABELS, EFFECTIVENESS_COLORS,
    VALID_TEST_TYPES, TEST_TYPE_LABELS,
    VALID_TEST_RESULTS, TEST_RESULT_LABELS, TEST_RESULT_COLORS,
    TEST_STATUS_SCHEDULED,
    IMPL_STATUS_IMPLEMENTED,
    AUDIT_ACTION_CREATE, AUDIT_ACTION_UPDATE, AUDIT_ACTION_DELETE,
    AUDIT_ENTITY_CONTROL, AUDIT_ENTITY_CONTROL_IMPL,
)
from app.services.auth_service import require_role, require_login
from app.services.audit_service import log_audit
from app.services import control_service as svc
from app.services import control_dashboard_service as dash_svc

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

    grouped = {}
    for c in controls:
        grouped.setdefault(c.domain, []).append(c)

    stats = svc.get_control_library_stats(db)

    control_ids = [c.id for c in controls]
    last_tested_map = svc.get_last_tested_dates(db, control_ids)

    return templates.TemplateResponse("control_library.html", {
        "request": request,
        "grouped": grouped,
        "stats": stats,
        "total_count": len(controls),
        "last_tested_map": last_tested_map,
        "domains": VALID_CONTROL_DOMAINS,
        "frameworks": AVAILABLE_FRAMEWORKS,
        "framework_display": FRAMEWORK_DISPLAY,
        "control_types": VALID_CONTROL_TYPES,
        "control_type_labels": CONTROL_TYPE_LABELS,
        "criticalities": VALID_CONTROL_CRITICALITIES,
        "frequency_labels": CONTROL_FREQUENCY_LABELS,
        "impl_type_labels": CONTROL_IMPL_TYPE_LABELS,
        "f_domain": domain,
        "f_framework": framework,
        "f_control_type": control_type,
        "f_criticality": criticality,
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
    return templates.TemplateResponse("control_dashboard.html", {
        "request": request,
        "data": data,
        "framework_display": FRAMEWORK_DISPLAY,
        "test_result_labels": TEST_RESULT_LABELS,
        "test_result_colors": TEST_RESULT_COLORS,
        "test_type_labels": TEST_TYPE_LABELS,
    })


@router.get("/controls/gap-analysis", response_class=HTMLResponse)
async def gap_analysis(
    request: Request,
    framework: str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    from app.services.control_dashboard_service import get_framework_coverage
    fw_coverage = get_framework_coverage(db)

    gaps = []
    if framework:
        controls_with_refs = svc.get_controls_by_framework(db, framework)
        for ctrl, ref in controls_with_refs:
            org_impl = db.query(ControlImplementation).filter(
                ControlImplementation.control_id == ctrl.id,
                ControlImplementation.vendor_id == None,
            ).first()
            gaps.append({
                "control": ctrl,
                "reference": ref,
                "implementation": org_impl,
                "status": org_impl.status if org_impl else "NOT_TRACKED",
            })

    return templates.TemplateResponse("gap_analysis.html", {
        "request": request,
        "gaps": gaps,
        "fw_coverage": fw_coverage,
        "frameworks": AVAILABLE_FRAMEWORKS,
        "framework_display": FRAMEWORK_DISPLAY,
        "f_framework": framework,
        "impl_status_labels": IMPL_STATUS_LABELS,
        "impl_status_colors": IMPL_STATUS_COLORS,
    })


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
        "scheduled_by_impl": scheduled_by_impl,
        "test_history": test_history,
        "kpi_overdue": testing_summary["overdue"],
        "kpi_upcoming": testing_summary["upcoming"],
        "kpi_scheduled": len(scheduled_tests),
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


@router.get("/controls/tests/{test_id}/complete", response_class=HTMLResponse)
async def control_test_complete_form(
    request: Request, test_id: int,
    db: Session = Depends(get_db), current_user: User = Depends(_analyst_dep),
):
    test = svc.get_test(db, test_id)
    if not test or test.status != TEST_STATUS_SCHEDULED:
        raise HTTPException(status_code=404, detail="Scheduled test not found")

    return templates.TemplateResponse("control_test_form.html", {
        "request": request,
        "impl": test.implementation,
        "completing_test": test,
        "test_types": VALID_TEST_TYPES,
        "test_type_labels": TEST_TYPE_LABELS,
        "test_results": VALID_TEST_RESULTS,
        "test_result_labels": TEST_RESULT_LABELS,
        "framework_display": FRAMEWORK_DISPLAY,
    })


@router.post("/controls/tests/{test_id}/complete", response_class=HTMLResponse)
async def control_test_complete(
    request: Request,
    test_id: int,
    result: str = Form(...),
    test_procedure: str = Form(""),
    findings: str = Form(""),
    recommendations: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    test = svc.get_test(db, test_id)
    if not test or test.status != TEST_STATUS_SCHEDULED:
        raise HTTPException(status_code=404, detail="Scheduled test not found")

    svc.complete_scheduled_test(
        db, test_id, result, test_procedure.strip(),
        findings.strip(), recommendations.strip(),
    )

    # Handle file uploads
    form = await request.form()
    files = form.getlist("evidence_files")
    for f in files:
        if hasattr(f, 'filename') and f.filename:
            ev = await svc.store_control_evidence(f, test_id)
            db.add(ev)

    log_audit(db, AUDIT_ACTION_UPDATE, "control_test",
              entity_id=test.id,
              entity_label=f"Completed test for {test.implementation.control.control_ref}",
              description=f"Completed scheduled test: {result}",
              actor_user=current_user)
    db.commit()

    return RedirectResponse(
        url=f"/controls/testing?tab=history&message={quote('Test completed')}&message_type=success",
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
async def control_detail(request: Request, control_id: int, db: Session = Depends(get_db), current_user: User = Depends(_analyst_dep)):
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

    return templates.TemplateResponse("control_detail.html", {
        "request": request,
        "control": ctrl,
        "implementations": impls,
        "last_tested_date": last_tested_date,
        "has_org_impl": has_org_impl,
        "users": users,
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
    request: Request, impl_id: int, db: Session = Depends(get_db), current_user: User = Depends(_analyst_dep),
):
    impl = svc.get_implementation(db, impl_id)
    if not impl:
        raise HTTPException(status_code=404, detail="Implementation not found")

    users = db.query(User).filter(User.is_active == True).order_by(User.display_name).all()

    return templates.TemplateResponse("control_impl_detail.html", {
        "request": request,
        "impl": impl,
        "users": users,
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

@router.get("/controls/implementations/{impl_id}/tests/new", response_class=HTMLResponse)
async def control_test_new(request: Request, impl_id: int, db: Session = Depends(get_db), current_user: User = Depends(_analyst_dep)):
    impl = svc.get_implementation(db, impl_id)
    if not impl:
        raise HTTPException(status_code=404, detail="Implementation not found")

    return templates.TemplateResponse("control_test_form.html", {
        "request": request,
        "impl": impl,
        "test_types": VALID_TEST_TYPES,
        "test_type_labels": TEST_TYPE_LABELS,
        "test_results": VALID_TEST_RESULTS,
        "test_result_labels": TEST_RESULT_LABELS,
        "framework_display": FRAMEWORK_DISPLAY,
    })


@router.post("/controls/implementations/{impl_id}/tests", response_class=HTMLResponse)
async def control_test_create(
    request: Request,
    impl_id: int,
    test_type: str = Form(...),
    test_procedure: str = Form(""),
    result: str = Form(...),
    findings: str = Form(""),
    recommendations: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    impl = svc.get_implementation(db, impl_id)
    if not impl:
        raise HTTPException(status_code=404, detail="Implementation not found")

    test = svc.create_test(
        db, impl_id, test_type, test_procedure.strip(),
        current_user.id, result, findings.strip(), recommendations.strip(),
    )

    # Handle file uploads
    form = await request.form()
    files = form.getlist("evidence_files")
    for f in files:
        if hasattr(f, 'filename') and f.filename:
            ev = await svc.store_control_evidence(f, test.id)
            db.add(ev)

    log_audit(db, AUDIT_ACTION_CREATE, "control_test",
              entity_id=test.id,
              entity_label=f"Test for {impl.control.control_ref}",
              description=f"Recorded {test_type} test: {result}",
              actor_user=current_user)
    db.commit()

    return RedirectResponse(
        url=f"/controls/implementations/{impl_id}?message={quote('Test recorded')}&message_type=success",
        status_code=303,
    )


@router.get("/controls/tests/{test_id}", response_class=HTMLResponse)
async def control_test_detail(request: Request, test_id: int, db: Session = Depends(get_db), current_user: User = Depends(_analyst_dep)):
    test = svc.get_test(db, test_id)
    if not test:
        raise HTTPException(status_code=404, detail="Test not found")

    return templates.TemplateResponse("control_test_detail.html", {
        "request": request,
        "test": test,
        "test_type_labels": TEST_TYPE_LABELS,
        "test_result_labels": TEST_RESULT_LABELS,
        "test_result_colors": TEST_RESULT_COLORS,
        "framework_display": FRAMEWORK_DISPLAY,
    })


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
