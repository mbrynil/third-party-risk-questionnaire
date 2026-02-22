"""Risk assessment module — campaigns, item scoring, templates, risk intake."""

from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from datetime import datetime

from app import templates
from models import (
    get_db, User, Risk, RiskAssessment, RiskAssessmentItem, RiskIntake, RiskAssessmentTemplate,
    ControlImplementation, Control, Asset, Vendor, ScenarioControlLink, RiskSimulationRun,
    VALID_RA_STATUSES, RA_STATUS_LABELS, RA_STATUS_COLORS,
    VALID_RAI_STATUSES, RAI_STATUS_LABELS, RAI_STATUS_COLORS,
    VALID_ASSESSMENT_METHODOLOGIES, ASSESSMENT_METHODOLOGY_LABELS,
    VALID_INTAKE_STATUSES, INTAKE_STATUS_LABELS, INTAKE_STATUS_COLORS,
    VALID_INTAKE_SEVERITIES, INTAKE_SEVERITY_LABELS, INTAKE_SEVERITY_COLORS,
    VALID_RISK_SOURCES, RISK_SOURCE_LABELS,
    VALID_CONFIDENCE_LEVELS, CONFIDENCE_LEVEL_LABELS,
    LIKELIHOOD_DESCRIPTORS, IMPACT_DESCRIPTORS,
    get_risk_level_label, RISK_LEVEL_COLORS,
    VALID_CONTROL_DOMAINS,
    VALID_SIMULATION_DISTRIBUTIONS, SIMULATION_DISTRIBUTION_LABELS,
    VALID_TREATMENT_DECISIONS, TREATMENT_DECISION_LABELS,
    EFFECTIVENESS_LABELS,
    AUDIT_ACTION_CREATE, AUDIT_ACTION_UPDATE, AUDIT_ACTION_DELETE, AUDIT_ACTION_STATUS_CHANGE,
    AUDIT_ENTITY_RISK_ASSESSMENT, AUDIT_ENTITY_RISK_INTAKE,
)
from app.services.auth_service import require_role, require_login
from app.services.audit_service import log_audit
from app.services import risk_assessment_service as ra_svc
from app.services import risk_intake_service as intake_svc
from app.services import monte_carlo_service as mc_svc

router = APIRouter()
_analyst_dep = require_role("admin", "analyst")
_admin_dep = require_role("admin")


# ==================== ASSESSMENT CAMPAIGN LIST ====================

@router.get("/risk-assessments", response_class=HTMLResponse)
async def assessment_list(
    request: Request,
    status: str = None,
    methodology: str = None,
    lead_id: int = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "analyst")),
):
    assessments = ra_svc.get_all_assessments(db, status=status, methodology=methodology,
                                              lead_id=lead_id)
    users = db.query(User).filter(User.is_active == True).order_by(User.display_name).all()

    # Compute assessment-level stats for KPIs
    all_assessments = db.query(RiskAssessment).filter(RiskAssessment.is_active == True).all()
    stats = {
        "total": len(all_assessments),
        "active": sum(1 for a in all_assessments if a.status in ("DRAFT", "IN_PROGRESS")),
        "under_review": sum(1 for a in all_assessments if a.status == "UNDER_REVIEW"),
        "completed": sum(1 for a in all_assessments if a.status == "COMPLETED"),
    }

    return templates.TemplateResponse("risk_assessment_list.html", {
        "request": request,
        "assessments": assessments,
        "users": users,
        "stats": stats,
        "filters": {"status": status, "methodology": methodology, "lead_id": lead_id},
        "VALID_RA_STATUSES": VALID_RA_STATUSES,
        "RA_STATUS_LABELS": RA_STATUS_LABELS,
        "RA_STATUS_COLORS": RA_STATUS_COLORS,
        "VALID_ASSESSMENT_METHODOLOGIES": VALID_ASSESSMENT_METHODOLOGIES,
        "ASSESSMENT_METHODOLOGY_LABELS": ASSESSMENT_METHODOLOGY_LABELS,
    })


# ==================== DASHBOARD ====================

@router.get("/risk-assessments/dashboard", response_class=HTMLResponse)
async def assessment_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_login),
):
    data = ra_svc.get_dashboard_data(db)

    # Transform for template expectations
    # active_campaigns and completed_count
    data["active_campaigns"] = data["by_status"].get("DRAFT", 0) + data["by_status"].get("IN_PROGRESS", 0)
    data["completed_count"] = data["by_status"].get("COMPLETED", 0)

    # avg_completion_rate
    if data["total_assessments"] > 0 and data.get("overall_stats"):
        data["avg_completion_rate"] = data["overall_stats"].get("completion_pct", 0)
    else:
        data["avg_completion_rate"] = 0

    # status_breakdown as list of tuples: (key, label, color, count)
    data["status_breakdown"] = [
        (s, RA_STATUS_LABELS.get(s, s), RA_STATUS_COLORS.get(s, "#6c757d"), data["by_status"].get(s, 0))
        for s in VALID_RA_STATUSES
        if data["by_status"].get(s, 0) > 0
    ]

    # methodology_distribution as list of tuples: (key, label, count, icon)
    meth_icons = {"QUALITATIVE": "bi-columns-gap", "QUANTITATIVE": "bi-currency-dollar", "SEMI_QUANTITATIVE": "bi-diagram-3"}
    data["methodology_distribution"] = [
        (m, ASSESSMENT_METHODOLOGY_LABELS.get(m, m), data["by_methodology"].get(m, 0), meth_icons.get(m, "bi-question"))
        for m in VALID_ASSESSMENT_METHODOLOGIES
        if data["by_methodology"].get(m, 0) > 0
    ]

    # active_spotlight
    data["active_spotlight"] = data.get("active_campaign")

    return templates.TemplateResponse("risk_assessment_dashboard.html", {
        "request": request,
        "data": data,
        "VALID_RA_STATUSES": VALID_RA_STATUSES,
        "RA_STATUS_LABELS": RA_STATUS_LABELS,
        "RA_STATUS_COLORS": RA_STATUS_COLORS,
        "VALID_ASSESSMENT_METHODOLOGIES": VALID_ASSESSMENT_METHODOLOGIES,
        "ASSESSMENT_METHODOLOGY_LABELS": ASSESSMENT_METHODOLOGY_LABELS,
        "get_risk_level_label": get_risk_level_label,
        "RISK_LEVEL_COLORS": RISK_LEVEL_COLORS,
    })


# ==================== CREATE ====================

@router.get("/risk-assessments/new", response_class=HTMLResponse)
async def assessment_new_form(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    users = db.query(User).filter(User.is_active == True).order_by(User.display_name).all()
    tmpl_list = db.query(RiskAssessmentTemplate).filter(
        RiskAssessmentTemplate.is_active == True
    ).order_by(RiskAssessmentTemplate.name).all()
    return templates.TemplateResponse("risk_assessment_form.html", {
        "request": request,
        "assessment": None,
        "users": users,
        "templates_list": tmpl_list,
        "VALID_ASSESSMENT_METHODOLOGIES": VALID_ASSESSMENT_METHODOLOGIES,
        "ASSESSMENT_METHODOLOGY_LABELS": ASSESSMENT_METHODOLOGY_LABELS,
    })


@router.post("/risk-assessments/new", response_class=HTMLResponse)
async def assessment_create(
    request: Request,
    title: str = Form(...),
    description: str = Form(None),
    scope: str = Form(None),
    methodology: str = Form("QUALITATIVE"),
    lead_user_id: int = Form(None),
    assessment_period_start: str = Form(None),
    assessment_period_end: str = Form(None),
    due_date: str = Form(None),
    risk_appetite_threshold: int = Form(10),
    notes: str = Form(None),
    template_id: int = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    period_start = datetime.strptime(assessment_period_start, "%Y-%m-%d") if assessment_period_start else None
    period_end = datetime.strptime(assessment_period_end, "%Y-%m-%d") if assessment_period_end else None
    due_dt = datetime.strptime(due_date, "%Y-%m-%d") if due_date else None

    # If a template is selected, apply its defaults for any empty fields
    if template_id:
        tmpl = db.query(RiskAssessmentTemplate).filter(
            RiskAssessmentTemplate.id == template_id
        ).first()
        if tmpl:
            if not methodology or methodology == "QUALITATIVE":
                methodology = tmpl.methodology
            if not scope:
                scope = tmpl.default_scope
            if risk_appetite_threshold == 10 and tmpl.default_risk_appetite:
                risk_appetite_threshold = tmpl.default_risk_appetite

    assessment = ra_svc.create_assessment(
        db,
        title=title, description=description, scope=scope,
        methodology=methodology, lead_user_id=lead_user_id,
        assessment_period_start=period_start, assessment_period_end=period_end,
        due_date=due_dt, risk_appetite_threshold=risk_appetite_threshold,
        notes=notes,
    )
    log_audit(db, action=AUDIT_ACTION_CREATE, entity_type=AUDIT_ENTITY_RISK_ASSESSMENT,
              entity_id=assessment.id, entity_label=assessment.assessment_ref,
              new_value={"title": title, "methodology": methodology}, actor_user=current_user)
    db.commit()
    return RedirectResponse(url=f"/risk-assessments/{assessment.id}", status_code=303)


# ==================== TEMPLATES (METHODOLOGY) ====================

@router.get("/risk-assessments/templates", response_class=HTMLResponse)
async def template_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    tmpl_list = db.query(RiskAssessmentTemplate).filter(
        RiskAssessmentTemplate.is_active == True
    ).order_by(RiskAssessmentTemplate.name).all()
    return templates.TemplateResponse("risk_assessment_templates.html", {
        "request": request,
        "templates_list": tmpl_list,
        "VALID_ASSESSMENT_METHODOLOGIES": VALID_ASSESSMENT_METHODOLOGIES,
        "ASSESSMENT_METHODOLOGY_LABELS": ASSESSMENT_METHODOLOGY_LABELS,
    })


@router.get("/risk-assessments/templates/new", response_class=HTMLResponse)
async def template_new_form(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    return templates.TemplateResponse("risk_assessment_template_form.html", {
        "request": request,
        "template": None,
        "VALID_ASSESSMENT_METHODOLOGIES": VALID_ASSESSMENT_METHODOLOGIES,
        "ASSESSMENT_METHODOLOGY_LABELS": ASSESSMENT_METHODOLOGY_LABELS,
    })


@router.post("/risk-assessments/templates/new", response_class=HTMLResponse)
async def template_create(
    request: Request,
    name: str = Form(...),
    description: str = Form(None),
    methodology: str = Form("QUALITATIVE"),
    default_risk_appetite: int = Form(10),
    default_scope: str = Form(None),
    criteria_json: str = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    tmpl = RiskAssessmentTemplate(
        name=name,
        description=description,
        methodology=methodology,
        default_risk_appetite=default_risk_appetite,
        default_scope=default_scope,
        criteria_json=criteria_json or None,
        created_by_user_id=current_user.id,
    )
    db.add(tmpl)
    db.flush()
    log_audit(db, action=AUDIT_ACTION_CREATE, entity_type=AUDIT_ENTITY_RISK_ASSESSMENT,
              entity_id=tmpl.id, entity_label=tmpl.name,
              description="Created assessment template",
              new_value={"name": name, "methodology": methodology}, actor_user=current_user)
    db.commit()
    return RedirectResponse(url="/risk-assessments/templates", status_code=303)


@router.post("/risk-assessments/templates/{tmpl_id}/delete", response_class=HTMLResponse)
async def template_delete(
    request: Request,
    tmpl_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_admin_dep),
):
    tmpl = db.query(RiskAssessmentTemplate).filter(RiskAssessmentTemplate.id == tmpl_id).first()
    if tmpl:
        log_audit(db, action=AUDIT_ACTION_DELETE, entity_type=AUDIT_ENTITY_RISK_ASSESSMENT,
                  entity_id=tmpl.id, entity_label=tmpl.name,
                  description="Deleted assessment template",
                  actor_user=current_user)
        tmpl.is_active = False
        db.commit()
    return RedirectResponse(url="/risk-assessments/templates", status_code=303)


# ==================== RISK INTAKE ====================

@router.get("/risk-assessments/intake", response_class=HTMLResponse)
async def intake_list(
    request: Request,
    status: str = None,
    severity: str = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_login),
):
    intakes = intake_svc.get_all_intakes(db, status=status)
    # Compute intake stats for KPI row
    intake_stats = intake_svc.get_intake_stats(db)
    stats = {
        "total": intake_stats["total"],
        "pending": intake_stats.get("pending_review", 0),
        "accepted": intake_stats["by_status"].get("ACCEPTED", 0),
        "converted": intake_stats["by_status"].get("CONVERTED", 0),
    }
    return templates.TemplateResponse("risk_intake_list.html", {
        "request": request,
        "intakes": intakes,
        "stats": stats,
        "filters": {"status": status, "severity": severity},
        "VALID_INTAKE_STATUSES": VALID_INTAKE_STATUSES,
        "INTAKE_STATUS_LABELS": INTAKE_STATUS_LABELS,
        "INTAKE_STATUS_COLORS": INTAKE_STATUS_COLORS,
        "VALID_INTAKE_SEVERITIES": VALID_INTAKE_SEVERITIES,
        "INTAKE_SEVERITY_LABELS": INTAKE_SEVERITY_LABELS,
        "INTAKE_SEVERITY_COLORS": INTAKE_SEVERITY_COLORS,
    })


@router.get("/risk-assessments/intake/new", response_class=HTMLResponse)
async def intake_new_form(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_login),
):
    users = db.query(User).filter(User.is_active == True).order_by(User.display_name).all()
    return templates.TemplateResponse("risk_intake_form.html", {
        "request": request,
        "intake": None,
        "users": users,
        "VALID_INTAKE_SEVERITIES": VALID_INTAKE_SEVERITIES,
        "INTAKE_SEVERITY_LABELS": INTAKE_SEVERITY_LABELS,
        "VALID_RISK_SOURCES": VALID_RISK_SOURCES,
        "RISK_SOURCE_LABELS": RISK_SOURCE_LABELS,
        "VALID_CONTROL_DOMAINS": VALID_CONTROL_DOMAINS,
    })


@router.post("/risk-assessments/intake/new", response_class=HTMLResponse)
async def intake_create(
    request: Request,
    title: str = Form(...),
    description: str = Form(None),
    risk_category: str = Form(None),
    risk_source: str = Form(None),
    initial_severity: str = Form(None),
    business_context: str = Form(None),
    potential_impact: str = Form(None),
    affected_assets: str = Form(None),
    suggested_owner_user_id: int = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_login),
):
    intake = intake_svc.create_intake(
        db,
        title=title, description=description,
        risk_category=risk_category, risk_source=risk_source,
        initial_severity=initial_severity,
        business_context=business_context,
        potential_impact=potential_impact,
        affected_assets=affected_assets,
        suggested_owner_user_id=suggested_owner_user_id,
        submitter_user_id=current_user.id,
    )
    log_audit(db, action=AUDIT_ACTION_CREATE, entity_type=AUDIT_ENTITY_RISK_INTAKE,
              entity_id=intake.id, entity_label=intake.intake_ref,
              new_value={"title": title, "severity": initial_severity}, actor_user=current_user)
    db.commit()
    return RedirectResponse(url=f"/risk-assessments/intake/{intake.id}", status_code=303)


@router.get("/risk-assessments/intake/{intake_id}", response_class=HTMLResponse)
async def intake_detail(
    request: Request,
    intake_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_login),
):
    intake = intake_svc.get_intake(db, intake_id)
    if not intake:
        raise HTTPException(status_code=404, detail="Risk intake not found")
    users = db.query(User).filter(User.is_active == True).order_by(User.display_name).all()
    return templates.TemplateResponse("risk_intake_detail.html", {
        "request": request,
        "intake": intake,
        "users": users,
        "VALID_INTAKE_STATUSES": VALID_INTAKE_STATUSES,
        "INTAKE_STATUS_LABELS": INTAKE_STATUS_LABELS,
        "INTAKE_STATUS_COLORS": INTAKE_STATUS_COLORS,
        "INTAKE_SEVERITY_LABELS": INTAKE_SEVERITY_LABELS,
        "INTAKE_SEVERITY_COLORS": INTAKE_SEVERITY_COLORS,
        "RISK_SOURCE_LABELS": RISK_SOURCE_LABELS,
    })


@router.post("/risk-assessments/intake/{intake_id}/review", response_class=HTMLResponse)
async def intake_review(
    request: Request,
    intake_id: int,
    status: str = Form(...),
    reviewer_notes: str = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    decision = "accept" if status == "ACCEPTED" else "reject"
    intake = intake_svc.review_intake(
        db, intake_id,
        reviewer_user_id=current_user.id,
        decision=decision,
        reviewer_notes=reviewer_notes,
    )
    if not intake:
        raise HTTPException(status_code=404, detail="Risk intake not found")
    log_audit(db, action=AUDIT_ACTION_STATUS_CHANGE, entity_type=AUDIT_ENTITY_RISK_INTAKE,
              entity_id=intake.id, entity_label=intake.intake_ref,
              new_value={"status": status}, actor_user=current_user)
    db.commit()
    return RedirectResponse(url=f"/risk-assessments/intake/{intake_id}", status_code=303)


@router.post("/risk-assessments/intake/{intake_id}/convert", response_class=HTMLResponse)
async def intake_convert(
    request: Request,
    intake_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    intake = intake_svc.get_intake(db, intake_id)
    if not intake:
        raise HTTPException(status_code=404, detail="Risk intake not found")

    intake_result, risk = intake_svc.convert_to_risk(db, intake_id, owner_user_id=current_user.id)
    if not risk:
        return RedirectResponse(
            url=f"/risk-assessments/intake/{intake_id}?message=Cannot convert — intake must be accepted first&message_type=danger",
            status_code=303,
        )
    log_audit(db, action=AUDIT_ACTION_STATUS_CHANGE, entity_type=AUDIT_ENTITY_RISK_INTAKE,
              entity_id=intake.id, entity_label=intake.intake_ref,
              new_value={"status": "CONVERTED", "risk_id": risk.id, "risk_ref": risk.risk_ref},
              actor_user=current_user)
    db.commit()
    return RedirectResponse(
        url=f"/risks/{risk.id}?message=Created from intake {intake.intake_ref}&message_type=success",
        status_code=303,
    )


# ==================== DETAIL ====================

@router.get("/risk-assessments/{assessment_id}", response_class=HTMLResponse)
async def assessment_detail(
    request: Request,
    assessment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_login),
):
    assessment = ra_svc.get_assessment(db, assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Risk assessment not found")
    # Available risks for adding (active, not already in this assessment)
    existing_risk_ids = [item.risk_id for item in assessment.items]
    available_risks = db.query(Risk).filter(
        Risk.is_active == True,
        ~Risk.id.in_(existing_risk_ids) if existing_risk_ids else True,
    ).order_by(Risk.risk_ref).all()
    users = db.query(User).filter(User.is_active == True).order_by(User.display_name).all()
    return templates.TemplateResponse("risk_assessment_detail.html", {
        "request": request,
        "assessment": assessment,
        "available_risks": available_risks,
        "users": users,
        "now": datetime.utcnow(),
        "VALID_RA_STATUSES": VALID_RA_STATUSES,
        "RA_STATUS_LABELS": RA_STATUS_LABELS,
        "RA_STATUS_COLORS": RA_STATUS_COLORS,
        "VALID_RAI_STATUSES": VALID_RAI_STATUSES,
        "RAI_STATUS_LABELS": RAI_STATUS_LABELS,
        "RAI_STATUS_COLORS": RAI_STATUS_COLORS,
        "ASSESSMENT_METHODOLOGY_LABELS": ASSESSMENT_METHODOLOGY_LABELS,
        "get_risk_level_label": get_risk_level_label,
        "RISK_LEVEL_COLORS": RISK_LEVEL_COLORS,
    })


# ==================== EDIT ====================

@router.get("/risk-assessments/{assessment_id}/edit", response_class=HTMLResponse)
async def assessment_edit_form(
    request: Request,
    assessment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    assessment = ra_svc.get_assessment(db, assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Risk assessment not found")
    users = db.query(User).filter(User.is_active == True).order_by(User.display_name).all()
    tmpl_list = db.query(RiskAssessmentTemplate).filter(
        RiskAssessmentTemplate.is_active == True
    ).order_by(RiskAssessmentTemplate.name).all()
    return templates.TemplateResponse("risk_assessment_form.html", {
        "request": request,
        "assessment": assessment,
        "users": users,
        "templates_list": tmpl_list,
        "VALID_ASSESSMENT_METHODOLOGIES": VALID_ASSESSMENT_METHODOLOGIES,
        "ASSESSMENT_METHODOLOGY_LABELS": ASSESSMENT_METHODOLOGY_LABELS,
    })


@router.post("/risk-assessments/{assessment_id}/edit", response_class=HTMLResponse)
async def assessment_edit(
    request: Request,
    assessment_id: int,
    title: str = Form(...),
    description: str = Form(None),
    scope: str = Form(None),
    methodology: str = Form("QUALITATIVE"),
    lead_user_id: int = Form(None),
    assessment_period_start: str = Form(None),
    assessment_period_end: str = Form(None),
    due_date: str = Form(None),
    risk_appetite_threshold: int = Form(10),
    notes: str = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    period_start = datetime.strptime(assessment_period_start, "%Y-%m-%d") if assessment_period_start else None
    period_end = datetime.strptime(assessment_period_end, "%Y-%m-%d") if assessment_period_end else None
    due_dt = datetime.strptime(due_date, "%Y-%m-%d") if due_date else None

    assessment = ra_svc.update_assessment(
        db, assessment_id,
        title=title, description=description, scope=scope,
        methodology=methodology, lead_user_id=lead_user_id,
        assessment_period_start=period_start, assessment_period_end=period_end,
        due_date=due_dt, risk_appetite_threshold=risk_appetite_threshold,
        notes=notes,
    )
    if not assessment:
        raise HTTPException(status_code=404, detail="Risk assessment not found")
    log_audit(db, action=AUDIT_ACTION_UPDATE, entity_type=AUDIT_ENTITY_RISK_ASSESSMENT,
              entity_id=assessment.id, entity_label=assessment.assessment_ref,
              new_value={"title": title}, actor_user=current_user)
    db.commit()
    return RedirectResponse(url=f"/risk-assessments/{assessment_id}", status_code=303)


# ==================== DELETE ====================

@router.post("/risk-assessments/{assessment_id}/delete", response_class=HTMLResponse)
async def assessment_delete(
    request: Request,
    assessment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_admin_dep),
):
    assessment = db.query(RiskAssessment).filter(RiskAssessment.id == assessment_id).first()
    if assessment:
        log_audit(db, action=AUDIT_ACTION_DELETE, entity_type=AUDIT_ENTITY_RISK_ASSESSMENT,
                  entity_id=assessment.id, entity_label=assessment.assessment_ref,
                  actor_user=current_user)
        ra_svc.delete_assessment(db, assessment_id)
        db.commit()
    return RedirectResponse(url="/risk-assessments", status_code=303)


# ==================== STATUS UPDATE ====================

@router.post("/risk-assessments/{assessment_id}/status", response_class=HTMLResponse)
async def assessment_status_update(
    request: Request,
    assessment_id: int,
    status: str = Form(...),
    notes: str = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    assessment, error = ra_svc.update_status(db, assessment_id, status,
                                              user_id=current_user.id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Risk assessment not found")
    if error:
        return RedirectResponse(
            url=f"/risk-assessments/{assessment_id}?message={error}&message_type=danger",
            status_code=303,
        )
    log_audit(db, action=AUDIT_ACTION_STATUS_CHANGE, entity_type=AUDIT_ENTITY_RISK_ASSESSMENT,
              entity_id=assessment.id, entity_label=assessment.assessment_ref,
              new_value={"status": status}, actor_user=current_user)
    db.commit()
    return RedirectResponse(url=f"/risk-assessments/{assessment_id}", status_code=303)


# ==================== ADD RISKS TO ASSESSMENT ====================

@router.post("/risk-assessments/{assessment_id}/add-risks", response_class=HTMLResponse)
async def assessment_add_risks(
    request: Request,
    assessment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    assessment = ra_svc.get_assessment(db, assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Risk assessment not found")
    form = await request.form()
    risk_ids = [int(x) for x in form.getlist("risk_ids") if x]
    if risk_ids:
        ra_svc.add_risks_to_assessment(db, assessment_id, risk_ids)
        log_audit(db, action=AUDIT_ACTION_UPDATE, entity_type=AUDIT_ENTITY_RISK_ASSESSMENT,
                  entity_id=assessment_id, entity_label=assessment.assessment_ref,
                  description=f"Added {len(risk_ids)} risk(s) to assessment",
                  actor_user=current_user)
        db.commit()
    return RedirectResponse(url=f"/risk-assessments/{assessment_id}", status_code=303)


# ==================== REMOVE ITEM ====================

@router.post("/risk-assessments/{assessment_id}/remove-item/{item_id}", response_class=HTMLResponse)
async def assessment_remove_item(
    request: Request,
    assessment_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    assessment = ra_svc.get_assessment(db, assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Risk assessment not found")
    ra_svc.remove_item(db, item_id)
    log_audit(db, action=AUDIT_ACTION_UPDATE, entity_type=AUDIT_ENTITY_RISK_ASSESSMENT,
              entity_id=assessment_id, entity_label=assessment.assessment_ref,
              description=f"Removed item {item_id} from assessment",
              actor_user=current_user)
    db.commit()
    return RedirectResponse(url=f"/risk-assessments/{assessment_id}", status_code=303)


# ==================== BULK ASSIGN ASSESSORS ====================

@router.post("/risk-assessments/{assessment_id}/assign", response_class=HTMLResponse)
async def assessment_bulk_assign(
    request: Request,
    assessment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    assessment = ra_svc.get_assessment(db, assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Risk assessment not found")
    form = await request.form()
    # Parse item_id -> user_id assignments from form
    assignments = {}
    for key in form.keys():
        if key.startswith("assessor_"):
            try:
                item_id = int(key.replace("assessor_", ""))
                user_id = int(form[key]) if form[key] else None
                assignments[item_id] = user_id
            except (ValueError, TypeError):
                continue
    if assignments:
        ra_svc.assign_assessors(db, assessment_id, assignments)
        log_audit(db, action=AUDIT_ACTION_UPDATE, entity_type=AUDIT_ENTITY_RISK_ASSESSMENT,
                  entity_id=assessment_id, entity_label=assessment.assessment_ref,
                  description=f"Bulk-assigned assessors for {len(assignments)} item(s)",
                  actor_user=current_user)
        db.commit()
    return RedirectResponse(url=f"/risk-assessments/{assessment_id}", status_code=303)


# ==================== ITEM SCORING FORM ====================

@router.get("/risk-assessments/{assessment_id}/items/{item_id}", response_class=HTMLResponse)
async def assessment_item_form(
    request: Request,
    assessment_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    assessment = ra_svc.get_assessment(db, assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Risk assessment not found")
    item = ra_svc.get_item_with_simulation(db, item_id)
    if not item or item.assessment_id != assessment_id:
        raise HTTPException(status_code=404, detail="Assessment item not found")

    # For FAIR analysis: org-level control implementations, assets, vendors
    control_implementations = db.query(ControlImplementation).join(Control).order_by(Control.control_ref).all()
    assets = db.query(Asset).filter(Asset.is_active == True).order_by(Asset.name).all()
    vendors = db.query(Vendor).filter(Vendor.status == "ACTIVE").order_by(Vendor.name).all()

    # Latest simulation run
    latest_sim = item.simulation_runs[0] if item.simulation_runs else None

    return templates.TemplateResponse("risk_assessment_item.html", {
        "request": request,
        "assessment": assessment,
        "item": item,
        "methodology": assessment.methodology,
        "VALID_CONFIDENCE_LEVELS": VALID_CONFIDENCE_LEVELS,
        "CONFIDENCE_LEVEL_LABELS": CONFIDENCE_LEVEL_LABELS,
        "LIKELIHOOD_DESCRIPTORS": LIKELIHOOD_DESCRIPTORS,
        "IMPACT_DESCRIPTORS": IMPACT_DESCRIPTORS,
        "get_risk_level_label": get_risk_level_label,
        "RISK_LEVEL_COLORS": RISK_LEVEL_COLORS,
        "control_implementations": control_implementations,
        "assets": assets,
        "vendors": vendors,
        "latest_sim": latest_sim,
        "VALID_TREATMENT_DECISIONS": VALID_TREATMENT_DECISIONS,
        "TREATMENT_DECISION_LABELS": TREATMENT_DECISION_LABELS,
        "EFFECTIVENESS_LABELS": EFFECTIVENESS_LABELS,
        "VALID_SIMULATION_DISTRIBUTIONS": VALID_SIMULATION_DISTRIBUTIONS,
        "SIMULATION_DISTRIBUTION_LABELS": SIMULATION_DISTRIBUTION_LABELS,
    })


# ==================== SUBMIT ITEM SCORES ====================

@router.post("/risk-assessments/{assessment_id}/items/{item_id}/assess", response_class=HTMLResponse)
async def assessment_item_assess(
    request: Request,
    assessment_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    assessment = ra_svc.get_assessment(db, assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Risk assessment not found")
    item = db.query(RiskAssessmentItem).filter(
        RiskAssessmentItem.id == item_id,
        RiskAssessmentItem.assessment_id == assessment_id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Assessment item not found")

    form = await request.form()
    scores = {}

    # Qualitative fields (for QUALITATIVE and SEMI_QUANTITATIVE)
    if assessment.methodology in ("QUALITATIVE", "SEMI_QUANTITATIVE"):
        likelihood = form.get("likelihood")
        impact = form.get("impact")
        residual_likelihood = form.get("residual_likelihood")
        residual_impact = form.get("residual_impact")
        scores["likelihood"] = int(likelihood) if likelihood else None
        scores["impact"] = int(impact) if impact else None
        scores["residual_likelihood"] = int(residual_likelihood) if residual_likelihood else None
        scores["residual_impact"] = int(residual_impact) if residual_impact else None

    # Quantitative fields (for QUANTITATIVE and SEMI_QUANTITATIVE)
    if assessment.methodology in ("QUANTITATIVE", "SEMI_QUANTITATIVE"):
        asset_value = form.get("asset_value")
        exposure_factor = form.get("exposure_factor")
        aro = form.get("annual_rate_of_occurrence")
        scores["asset_value"] = float(asset_value) if asset_value else None
        scores["exposure_factor"] = float(exposure_factor) if exposure_factor else None
        scores["annual_rate_of_occurrence"] = float(aro) if aro else None

    # FAIR factor fields (for QUANTITATIVE and SEMI_QUANTITATIVE)
    if assessment.methodology in ("QUANTITATIVE", "SEMI_QUANTITATIVE"):
        fair_fields = [
            "tef_min", "tef_likely", "tef_max",
            "vuln_min", "vuln_likely", "vuln_max",
            "plm_min", "plm_likely", "plm_max",
            "slm_min", "slm_likely", "slm_max",
        ]
        for field in fair_fields:
            val = form.get(field)
            scores[field] = float(val) if val else None

        scores["asset_id"] = form.get("asset_id") or None
        scores["vendor_link_id"] = form.get("vendor_link_id") or None
        scores["treatment_decision"] = form.get("treatment_decision") or None
        scores["treatment_decision_rationale"] = form.get("treatment_decision_rationale") or None

    # Common fields (all methodologies)
    scores["confidence_level"] = form.get("confidence_level") or None
    scores["rationale"] = form.get("rationale") or None
    scores["existing_controls_notes"] = form.get("existing_controls_notes") or None
    scores["recommended_treatment"] = form.get("recommended_treatment") or None
    scores["findings"] = form.get("findings") or None

    ra_svc.assess_item(db, item_id, **scores)
    log_audit(db, action=AUDIT_ACTION_UPDATE, entity_type=AUDIT_ENTITY_RISK_ASSESSMENT,
              entity_id=assessment_id, entity_label=assessment.assessment_ref,
              description=f"Assessed item {item_id} (risk: {item.risk.risk_ref if item.risk else item.risk_id})",
              actor_user=current_user)
    db.commit()
    return RedirectResponse(url=f"/risk-assessments/{assessment_id}", status_code=303)


# ==================== REVIEW ITEM ====================

@router.post("/risk-assessments/{assessment_id}/items/{item_id}/review", response_class=HTMLResponse)
async def assessment_item_review(
    request: Request,
    assessment_id: int,
    item_id: int,
    reviewer_notes: str = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    assessment = ra_svc.get_assessment(db, assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Risk assessment not found")
    item = db.query(RiskAssessmentItem).filter(
        RiskAssessmentItem.id == item_id,
        RiskAssessmentItem.assessment_id == assessment_id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Assessment item not found")

    ra_svc.review_item(db, item_id, reviewer_user_id=current_user.id, reviewer_notes=reviewer_notes)
    log_audit(db, action=AUDIT_ACTION_UPDATE, entity_type=AUDIT_ENTITY_RISK_ASSESSMENT,
              entity_id=assessment_id, entity_label=assessment.assessment_ref,
              description=f"Reviewed item {item_id}",
              actor_user=current_user)
    db.commit()
    return RedirectResponse(url=f"/risk-assessments/{assessment_id}", status_code=303)


# ==================== FINALIZE ASSESSMENT ====================

@router.post("/risk-assessments/{assessment_id}/finalize", response_class=HTMLResponse)
async def assessment_finalize(
    request: Request,
    assessment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    assessment = ra_svc.get_assessment(db, assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Risk assessment not found")

    stats = ra_svc.finalize_assessment(db, assessment_id)
    error = None
    if not stats or stats.get("applied", 0) == 0 and stats.get("skipped", 0) > 0:
        error = "No reviewed items to finalize"
    if error:
        return RedirectResponse(
            url=f"/risk-assessments/{assessment_id}?message={error}&message_type=danger",
            status_code=303,
        )
    log_audit(db, action=AUDIT_ACTION_STATUS_CHANGE, entity_type=AUDIT_ENTITY_RISK_ASSESSMENT,
              entity_id=assessment_id, entity_label=assessment.assessment_ref,
              new_value={"status": "COMPLETED", "risks_updated": stats.get("applied", 0)},
              actor_user=current_user)
    db.commit()
    return RedirectResponse(
        url=f"/risk-assessments/{assessment_id}?message=Assessment finalized — {stats.get('risks_updated', 0)} risk(s) updated&message_type=success",
        status_code=303,
    )


# ==================== REPORT ====================

@router.get("/risk-assessments/{assessment_id}/report", response_class=HTMLResponse)
async def assessment_report(
    request: Request,
    assessment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_login),
):
    assessment = ra_svc.get_assessment(db, assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Risk assessment not found")

    # Compute summary statistics for the report
    items = assessment.items
    total_items = len(items)
    assessed_items = [i for i in items if i.status in ("ASSESSED", "REVIEWED")]
    reviewed_items = [i for i in items if i.status == "REVIEWED"]

    # Qualitative summary
    scored_items = [i for i in items if i.inherent_score is not None]
    avg_inherent = sum(i.inherent_score for i in scored_items) / len(scored_items) if scored_items else 0
    residual_scored = [i for i in items if i.residual_score is not None]
    avg_residual = sum(i.residual_score for i in residual_scored) / len(residual_scored) if residual_scored else 0
    max_inherent = max((i.inherent_score for i in scored_items), default=0)

    # Quantitative summary
    ale_items = [i for i in items if i.annualized_loss_expectancy is not None]
    total_ale = sum(i.annualized_loss_expectancy for i in ale_items)

    # Risk level distribution
    level_distribution = {}
    for i in scored_items:
        level = get_risk_level_label(i.inherent_score)
        level_distribution[level] = level_distribution.get(level, 0) + 1

    # Items exceeding appetite
    threshold = assessment.risk_appetite_threshold or 10
    above_appetite = [i for i in scored_items if i.inherent_score and i.inherent_score >= threshold]

    stats = {
        "total_items": total_items,
        "assessed_count": len(assessed_items),
        "reviewed_count": len(reviewed_items),
        "completion_pct": round(len(assessed_items) / total_items * 100) if total_items else 0,
        "avg_inherent": round(avg_inherent, 1),
        "avg_inherent_score": round(avg_inherent, 1),
        "avg_residual": round(avg_residual, 1),
        "max_inherent": max_inherent,
        "total_ale": total_ale,
        "ale_count": len(ale_items),
        "level_distribution": level_distribution,
        "above_appetite_count": len(above_appetite),
        "above_appetite_items": above_appetite,
        "high_critical_count": len(above_appetite),
    }

    # Group items by risk level for the template
    items_by_level = {}
    for item in items:
        if item.inherent_score is not None:
            level = get_risk_level_label(item.inherent_score)
        else:
            level = "Very Low"
        items_by_level.setdefault(level, []).append(item)

    methodology_label = ASSESSMENT_METHODOLOGY_LABELS.get(assessment.methodology, assessment.methodology)

    return templates.TemplateResponse("risk_assessment_report.html", {
        "request": request,
        "assessment": assessment,
        "stats": stats,
        "items_by_level": items_by_level,
        "methodology_label": methodology_label,
        "VALID_RA_STATUSES": VALID_RA_STATUSES,
        "RA_STATUS_LABELS": RA_STATUS_LABELS,
        "RA_STATUS_COLORS": RA_STATUS_COLORS,
        "RAI_STATUS_LABELS": RAI_STATUS_LABELS,
        "RAI_STATUS_COLORS": RAI_STATUS_COLORS,
        "ASSESSMENT_METHODOLOGY_LABELS": ASSESSMENT_METHODOLOGY_LABELS,
        "CONFIDENCE_LEVEL_LABELS": CONFIDENCE_LEVEL_LABELS,
        "LIKELIHOOD_DESCRIPTORS": LIKELIHOOD_DESCRIPTORS,
        "IMPACT_DESCRIPTORS": IMPACT_DESCRIPTORS,
        "get_risk_level_label": get_risk_level_label,
        "RISK_LEVEL_COLORS": RISK_LEVEL_COLORS,
    })


# ==================== COMPARISON ====================

@router.get("/risk-assessments/{assessment_id}/compare", response_class=HTMLResponse)
async def assessment_compare(
    request: Request,
    assessment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_login),
):
    assessment = ra_svc.get_assessment(db, assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Risk assessment not found")

    comparison = ra_svc.get_comparison_data(db, assessment_id)

    return templates.TemplateResponse("risk_assessment_compare.html", {
        "request": request,
        "assessment": assessment,
        "comparison": comparison,
        "RA_STATUS_LABELS": RA_STATUS_LABELS,
        "RA_STATUS_COLORS": RA_STATUS_COLORS,
        "ASSESSMENT_METHODOLOGY_LABELS": ASSESSMENT_METHODOLOGY_LABELS,
        "get_risk_level_label": get_risk_level_label,
        "RISK_LEVEL_COLORS": RISK_LEVEL_COLORS,
    })


# ==================== MONTE CARLO SIMULATION ====================

@router.post("/risk-assessments/{assessment_id}/items/{item_id}/simulate", response_class=HTMLResponse)
async def run_simulation(
    request: Request,
    assessment_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    assessment = ra_svc.get_assessment(db, assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Risk assessment not found")
    item = db.query(RiskAssessmentItem).filter(
        RiskAssessmentItem.id == item_id,
        RiskAssessmentItem.assessment_id == assessment_id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Assessment item not found")

    form = await request.form()
    iterations = int(form.get("iterations", 10000))
    iterations = max(1000, min(50000, iterations))
    seed = form.get("seed")
    seed = int(seed) if seed else None
    distribution = form.get("distribution", "PERT")
    if distribution not in VALID_SIMULATION_DISTRIBUTIONS:
        distribution = "PERT"

    run = mc_svc.run_and_store(db, item_id, user_id=current_user.id,
                                iterations=iterations, seed=seed, distribution=distribution)
    if not run:
        return RedirectResponse(
            url=f"/risk-assessments/{assessment_id}/items/{item_id}?message=Missing FAIR factor inputs — fill all min/likely/max fields before simulating&message_type=danger",
            status_code=303,
        )

    log_audit(db, action=AUDIT_ACTION_UPDATE, entity_type=AUDIT_ENTITY_RISK_ASSESSMENT,
              entity_id=assessment_id, entity_label=assessment.assessment_ref,
              description=f"Ran Monte Carlo simulation ({iterations} iterations) on item {item_id}",
              actor_user=current_user)
    db.commit()
    return RedirectResponse(
        url=f"/risk-assessments/{assessment_id}/items/{item_id}/simulation/{run.id}",
        status_code=303,
    )


@router.get("/risk-assessments/{assessment_id}/items/{item_id}/simulation/{run_id}", response_class=HTMLResponse)
async def simulation_results(
    request: Request,
    assessment_id: int,
    item_id: int,
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_login),
):
    import json as json_lib
    assessment = ra_svc.get_assessment(db, assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Risk assessment not found")
    item = ra_svc.get_item_with_simulation(db, item_id)
    if not item or item.assessment_id != assessment_id:
        raise HTTPException(status_code=404, detail="Assessment item not found")

    run = db.query(RiskSimulationRun).filter(
        RiskSimulationRun.id == run_id,
        RiskSimulationRun.item_id == item_id,
    ).first()
    if not run:
        raise HTTPException(status_code=404, detail="Simulation run not found")

    histogram = json_lib.loads(run.histogram_json) if run.histogram_json else []
    exceedance = json_lib.loads(run.exceedance_json) if run.exceedance_json else []
    sensitivity = json_lib.loads(run.sensitivity_json) if run.sensitivity_json else []

    return templates.TemplateResponse("risk_simulation_results.html", {
        "request": request,
        "assessment": assessment,
        "item": item,
        "run": run,
        "histogram": histogram,
        "exceedance": exceedance,
        "sensitivity": sensitivity,
        "histogram_json": run.histogram_json or "[]",
        "exceedance_json": run.exceedance_json or "[]",
        "sensitivity_json": run.sensitivity_json or "[]",
        "ASSESSMENT_METHODOLOGY_LABELS": ASSESSMENT_METHODOLOGY_LABELS,
        "SIMULATION_DISTRIBUTION_LABELS": SIMULATION_DISTRIBUTION_LABELS,
        "EFFECTIVENESS_LABELS": EFFECTIVENESS_LABELS,
    })


@router.post("/risk-assessments/{assessment_id}/items/{item_id}/control-links", response_class=HTMLResponse)
async def save_control_links(
    request: Request,
    assessment_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    assessment = ra_svc.get_assessment(db, assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Risk assessment not found")
    item = db.query(RiskAssessmentItem).filter(
        RiskAssessmentItem.id == item_id,
        RiskAssessmentItem.assessment_id == assessment_id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Assessment item not found")

    form = await request.form()
    impl_ids = form.getlist("implementation_ids")

    # Delete existing links and recreate
    db.query(ScenarioControlLink).filter(ScenarioControlLink.item_id == item_id).delete()

    for impl_id_str in impl_ids:
        impl_id = int(impl_id_str)
        impl = db.query(ControlImplementation).filter(ControlImplementation.id == impl_id).first()
        if impl:
            weight_str = form.get(f"weight_{impl_id}", "1.0")
            weight = float(weight_str) if weight_str else 1.0
            weight = max(0.0, min(1.0, weight))
            link = ScenarioControlLink(
                item_id=item_id,
                implementation_id=impl_id,
                effectiveness_at_assessment=impl.effectiveness,
                weight=weight,
            )
            db.add(link)

    log_audit(db, action=AUDIT_ACTION_UPDATE, entity_type=AUDIT_ENTITY_RISK_ASSESSMENT,
              entity_id=assessment_id, entity_label=assessment.assessment_ref,
              description=f"Updated control links for item {item_id}",
              actor_user=current_user)
    db.commit()
    return RedirectResponse(
        url=f"/risk-assessments/{assessment_id}/items/{item_id}?message=Control links saved&message_type=success",
        status_code=303,
    )


@router.get("/risk-assessments/{assessment_id}/executive-summary", response_class=HTMLResponse)
async def executive_summary(
    request: Request,
    assessment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_login),
):
    summary = ra_svc.get_executive_summary_data(db, assessment_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Risk assessment not found")

    return templates.TemplateResponse("risk_executive_summary.html", {
        "request": request,
        "summary": summary,
        "assessment": summary["assessment"],
        "ASSESSMENT_METHODOLOGY_LABELS": ASSESSMENT_METHODOLOGY_LABELS,
        "RA_STATUS_LABELS": RA_STATUS_LABELS,
        "RA_STATUS_COLORS": RA_STATUS_COLORS,
        "get_risk_level_label": get_risk_level_label,
        "RISK_LEVEL_COLORS": RISK_LEVEL_COLORS,
        "TREATMENT_DECISION_LABELS": TREATMENT_DECISION_LABELS,
    })
