from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
import json

from app import templates
from models import (
    get_db, Assessment, Question, QuestionBankItem, ConditionalRule,
    VALID_CHOICES,
)
from app.services.token import generate_unique_token
from app.services.vendor_service import find_or_create_vendor

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("home.html", {"request": request})


@router.get("/create", response_class=HTMLResponse)
async def create_assessment_page(request: Request, db: Session = Depends(get_db)):
    question_bank = db.query(QuestionBankItem).filter(
        QuestionBankItem.is_active == True
    ).order_by(QuestionBankItem.category, QuestionBankItem.id).all()

    categories = {}
    for item in question_bank:
        if item.category not in categories:
            categories[item.category] = []
        categories[item.category].append(item)

    return templates.TemplateResponse("create.html", {
        "request": request,
        "categories": categories
    })


@router.post("/create")
async def create_assessment(
    request: Request,
    company_name: str = Form(...),
    title: str = Form(...),
    custom_questions: str = Form(""),
    db: Session = Depends(get_db)
):
    form_data = await request.form()
    question_ids = form_data.getlist("question_ids")

    if not question_ids and not custom_questions.strip():
        question_bank = db.query(QuestionBankItem).filter(
            QuestionBankItem.is_active == True
        ).order_by(QuestionBankItem.category, QuestionBankItem.id).all()
        categories = {}
        for item in question_bank:
            if item.category not in categories:
                categories[item.category] = []
            categories[item.category].append(item)
        return templates.TemplateResponse("create.html", {
            "request": request,
            "categories": categories,
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
                valid_expected = [v for v in expected_list if v in VALID_CHOICES]
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
                category=bank_item.category
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
