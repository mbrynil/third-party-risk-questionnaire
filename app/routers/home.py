from datetime import datetime

from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, Response as FastAPIResponse, StreamingResponse
from sqlalchemy.orm import Session
import json

from app import templates
from models import (
    get_db, Assessment, AssessmentTemplate, Question, QuestionBankItem, ConditionalRule, User,
    VALID_CHOICES, get_answer_options,
    Vendor,
)
from app.services.token import generate_unique_token
from app.services.vendor_service import find_or_create_vendor
from app.services.portfolio import get_portfolio_data
from app.services.remediation_service import get_portfolio_remediation_summary
from app.services.reminder_service import get_reminder_stats
from app.services.export_service import generate_portfolio_report_pdf, generate_vendor_list_csv
from app.services.auth_service import require_login, require_role

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def home(request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_login)):
    data = get_portfolio_data(db)
    templates_list = db.query(AssessmentTemplate).order_by(AssessmentTemplate.name).all()
    reminder_stats = get_reminder_stats(db)
    analysts = db.query(User).filter(
        User.is_active == True,
        User.role.in_(["admin", "analyst"]),
    ).order_by(User.display_name).all()
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "kpis": data["kpis"],
        "vendors": data["vendors"],
        "risk_distribution_json": json.dumps(data["risk_distribution"]),
        "decision_outcomes_json": json.dumps(data["decision_outcomes"]),
        "assessment_pipeline_json": json.dumps(data["assessment_pipeline"]),
        "category_analysis_json": json.dumps(data["category_analysis"]),
        "heatmap": data["heatmap"],
        "assessment_templates": templates_list,
        "reminder_stats": reminder_stats,
        "analysts": analysts,
    })


@router.get("/dashboard/report", response_class=HTMLResponse)
async def portfolio_report(request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_login)):
    data = get_portfolio_data(db)
    remediation_summary = get_portfolio_remediation_summary(db)
    return templates.TemplateResponse("portfolio_report.html", {
        "request": request,
        "kpis": data["kpis"],
        "vendors": data["vendors"],
        "risk_distribution": data["risk_distribution"],
        "decision_outcomes": data["decision_outcomes"],
        "assessment_pipeline": data["assessment_pipeline"],
        "category_analysis": data["category_analysis"],
        "remediation_summary": remediation_summary,
        "now": datetime.utcnow(),
    })


@router.get("/dashboard/report.pdf")
async def portfolio_report_pdf(db: Session = Depends(get_db), current_user: User = Depends(require_login)):
    data = get_portfolio_data(db)
    remediation_summary = get_portfolio_remediation_summary(db)
    template_ctx = {
        "kpis": data["kpis"],
        "vendors": data["vendors"],
        "risk_distribution": data["risk_distribution"],
        "decision_outcomes": data["decision_outcomes"],
        "assessment_pipeline": data["assessment_pipeline"],
        "category_analysis": data["category_analysis"],
        "remediation_summary": remediation_summary,
        "now": datetime.utcnow(),
    }
    try:
        pdf_bytes = generate_portfolio_report_pdf(template_ctx)
    except RuntimeError as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail=str(exc))
    filename = f"portfolio_report_{datetime.utcnow().strftime('%Y%m%d')}.pdf"
    return FastAPIResponse(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/dashboard/vendors.csv")
async def vendor_list_csv(db: Session = Depends(get_db), current_user: User = Depends(require_login)):
    csv_content = generate_vendor_list_csv(db)
    filename = f"vendors_{datetime.utcnow().strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/create", response_class=HTMLResponse)
async def create_assessment_page(request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_role("admin", "analyst"))):
    from models import Vendor, VENDOR_STATUS_ACTIVE

    question_bank = db.query(QuestionBankItem).filter(
        QuestionBankItem.is_active == True
    ).order_by(QuestionBankItem.category, QuestionBankItem.id).all()

    categories = {}
    for item in question_bank:
        if item.category not in categories:
            categories[item.category] = []
        categories[item.category].append(item)

    bank_item_options = {str(item.id): get_answer_options(item) for item in question_bank}

    vendors = db.query(Vendor).filter(
        Vendor.status == VENDOR_STATUS_ACTIVE
    ).order_by(Vendor.name).all()

    return templates.TemplateResponse("create.html", {
        "request": request,
        "categories": categories,
        "bank_item_options_json": json.dumps(bank_item_options),
        "vendors": vendors,
    })


@router.post("/create")
async def create_assessment(
    request: Request,
    company_name: str = Form(...),
    title: str = Form(...),
    custom_questions: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "analyst")),
):
    form_data = await request.form()
    question_ids = form_data.getlist("question_ids")

    if not question_ids and not custom_questions.strip():
        from models import Vendor, VENDOR_STATUS_ACTIVE
        question_bank = db.query(QuestionBankItem).filter(
            QuestionBankItem.is_active == True
        ).order_by(QuestionBankItem.category, QuestionBankItem.id).all()
        categories = {}
        for item in question_bank:
            if item.category not in categories:
                categories[item.category] = []
            categories[item.category].append(item)
        bank_item_options = {}
        for cat_items in categories.values():
            for item in cat_items:
                bank_item_options[str(item.id)] = get_answer_options(item)
        vendors = db.query(Vendor).filter(Vendor.status == VENDOR_STATUS_ACTIVE).order_by(Vendor.name).all()
        return templates.TemplateResponse("create.html", {
            "request": request,
            "categories": categories,
            "bank_item_options_json": json.dumps(bank_item_options),
            "vendors": vendors,
            "error": "Please select at least one question from the bank or add custom questions."
        })

    normalized_company_name = company_name.strip()
    normalized_title = title.strip()

    token = generate_unique_token(db)
    vendor = find_or_create_vendor(db, normalized_company_name)

    assessment = Assessment(
        company_name=normalized_company_name,
        title=normalized_title,
        token=token,
        vendor_id=vendor.id
    )
    db.add(assessment)
    db.flush()

    order = 0
    for qid in question_ids:
        bank_item = db.query(QuestionBankItem).filter(QuestionBankItem.id == int(str(qid))).first()
        if bank_item:
            weight = form_data.get(f"weight_{qid}", "MEDIUM")
            if weight not in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]:
                weight = "MEDIUM"
            expected_list = form_data.getlist(f"expected_{qid}[]")
            expected_values_json = None
            expected_value_single = None
            if expected_list:
                valid_opts = get_answer_options(bank_item)
                valid_expected = [v for v in expected_list if v in valid_opts]
                if valid_expected:
                    expected_values_json = json.dumps(valid_expected)
                    expected_value_single = valid_expected[0]
            answer_mode = form_data.get(f"answer_mode_{qid}", "SINGLE")
            if answer_mode not in ["SINGLE", "MULTI"]:
                answer_mode = "SINGLE"
            question = Question(
                assessment_id=assessment.id,
                question_text=bank_item.text,
                order=order,
                weight=weight,
                expected_operator="EQUALS",
                expected_value=expected_value_single,
                expected_values=expected_values_json,
                expected_value_type="CHOICE",
                answer_mode=answer_mode,
                category=bank_item.category,
                question_bank_item_id=bank_item.id,
                answer_options=bank_item.answer_options,
            )
            db.add(question)
            order += 1

    if custom_questions.strip():
        custom_lines = [q.strip() for q in custom_questions.strip().split('\n') if q.strip()]
        for q_text in custom_lines:
            question = Question(
                assessment_id=assessment.id,
                question_text=q_text,
                order=order,
                weight="MEDIUM",
                expected_operator="EQUALS",
                expected_value=None,
                expected_values=None,
                expected_value_type="CHOICE",
                answer_mode="SINGLE"
            )
            db.add(question)
            order += 1

    db.flush()

    created_questions = db.query(Question).filter(
        Question.assessment_id == assessment.id
    ).order_by(Question.order).all()

    question_id_map = {}
    for idx, qid in enumerate(question_ids):
        if idx < len(created_questions):
            question_id_map[str(qid)] = created_questions[idx].id

    conditional_rules_json = form_data.get("conditional_rules", "[]")
    try:
        rules_data = json.loads(conditional_rules_json)
        if isinstance(rules_data, list):
            for rule in rules_data:
                trigger_bank_id = str(rule.get("trigger_question_id", ""))
                target_bank_id = str(rule.get("target_question_id", ""))
                trigger_values = rule.get("trigger_values", [])
                make_required = rule.get("make_required", False)

                trigger_q_id = question_id_map.get(trigger_bank_id)
                target_q_id = question_id_map.get(target_bank_id)

                if trigger_q_id and target_q_id and trigger_values:
                    cond_rule = ConditionalRule(
                        assessment_id=assessment.id,
                        trigger_question_id=trigger_q_id,
                        operator="IN",
                        trigger_values=json.dumps(trigger_values),
                        target_question_id=target_q_id,
                        make_required=make_required
                    )
                    db.add(cond_rule)
    except (json.JSONDecodeError, TypeError):
        pass

    db.commit()

    base_url = str(request.base_url).rstrip('/')
    vendor_url = f"{base_url}/vendor/{token}"

    return templates.TemplateResponse("created.html", {
        "request": request,
        "assessment": assessment,
        "token": token,
        "vendor_url": vendor_url
    })
