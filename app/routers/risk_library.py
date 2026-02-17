from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from app import templates
import json as json_lib

from models import (
    get_db, RiskStatement, QuestionBankItem,
    VALID_TRIGGER_CONDITIONS, VALID_SEVERITIES, TRIGGER_LABELS,
    TRIGGER_QUESTION_ANSWERED, VALID_CHOICES, get_answer_options,
)

router = APIRouter()


def _get_categories(db: Session) -> list[str]:
    """Get distinct categories from the question bank, sorted."""
    rows = db.query(QuestionBankItem.category).distinct().order_by(QuestionBankItem.category).all()
    return [r[0] for r in rows]


def _get_question_bank_items(db: Session) -> list[dict]:
    """Get all active question bank items grouped info for dropdowns."""
    items = db.query(QuestionBankItem).filter(
        QuestionBankItem.is_active == True
    ).order_by(QuestionBankItem.category, QuestionBankItem.id).all()
    return [{"id": item.id, "text": item.text, "category": item.category} for item in items]


def _form_context(db: Session, statement=None, error=None):
    """Build common template context for the risk library edit form."""
    items = db.query(QuestionBankItem).filter(
        QuestionBankItem.is_active == True
    ).order_by(QuestionBankItem.category, QuestionBankItem.id).all()
    question_bank_items = [{"id": item.id, "text": item.text, "category": item.category} for item in items]
    answer_options_map = {item.id: get_answer_options(item) for item in items}
    return {
        "statement": statement,
        "categories": _get_categories(db),
        "trigger_conditions": VALID_TRIGGER_CONDITIONS,
        "trigger_labels": TRIGGER_LABELS,
        "severities": VALID_SEVERITIES,
        "question_bank_items": question_bank_items,
        "answer_choices": VALID_CHOICES,
        "answer_options_map": json_lib.dumps(answer_options_map),
        "error": error,
    }


@router.get("/risk-library", response_class=HTMLResponse)
async def risk_library_list(request: Request, db: Session = Depends(get_db)):
    statements = db.query(RiskStatement).options(
        joinedload(RiskStatement.trigger_question)
    ).order_by(RiskStatement.category, RiskStatement.severity).all()

    grouped = {}
    for stmt in statements:
        if stmt.category not in grouped:
            grouped[stmt.category] = []
        grouped[stmt.category].append(stmt)

    return templates.TemplateResponse("risk_library.html", {
        "request": request,
        "grouped": grouped,
        "trigger_labels": TRIGGER_LABELS,
        "total_count": len(statements),
    })


@router.get("/risk-library/new", response_class=HTMLResponse)
async def risk_library_new(request: Request, db: Session = Depends(get_db)):
    ctx = _form_context(db)
    ctx["request"] = request
    return templates.TemplateResponse("risk_library_edit.html", ctx)


@router.post("/risk-library/new", response_class=HTMLResponse)
async def risk_library_create(
    request: Request,
    category: str = Form(...),
    trigger_condition: str = Form(...),
    severity: str = Form(...),
    finding_text: str = Form(...),
    remediation_text: str = Form(...),
    trigger_question_id: str = Form(""),
    trigger_answer_value: str = Form(""),
    db: Session = Depends(get_db),
):
    # For QUESTION_ANSWERED, auto-derive category from the selected question
    if trigger_condition == TRIGGER_QUESTION_ANSWERED:
        if not trigger_question_id.strip() or not trigger_answer_value.strip():
            ctx = _form_context(db, error="Question and answer value are required for question-level triggers.")
            ctx["request"] = request
            return templates.TemplateResponse("risk_library_edit.html", ctx)

        bank_item = db.query(QuestionBankItem).filter(
            QuestionBankItem.id == int(trigger_question_id)
        ).first()
        if bank_item:
            category = bank_item.category

    if not category.strip() or not finding_text.strip() or not remediation_text.strip():
        ctx = _form_context(db, error="Category, finding text, and remediation text are required.")
        ctx["request"] = request
        return templates.TemplateResponse("risk_library_edit.html", ctx)

    stmt = RiskStatement(
        category=category.strip(),
        trigger_condition=trigger_condition,
        severity=severity,
        finding_text=finding_text.strip(),
        remediation_text=remediation_text.strip(),
        is_active=True,
        trigger_question_id=int(trigger_question_id) if trigger_condition == TRIGGER_QUESTION_ANSWERED and trigger_question_id.strip() else None,
        trigger_answer_value=trigger_answer_value.strip() if trigger_condition == TRIGGER_QUESTION_ANSWERED and trigger_answer_value.strip() else None,
    )
    db.add(stmt)
    db.commit()

    return RedirectResponse(
        url="/risk-library?message=Risk statement created&message_type=success",
        status_code=303,
    )


@router.get("/risk-library/{statement_id}/edit", response_class=HTMLResponse)
async def risk_library_edit(request: Request, statement_id: int, db: Session = Depends(get_db)):
    stmt = db.query(RiskStatement).options(
        joinedload(RiskStatement.trigger_question)
    ).filter(RiskStatement.id == statement_id).first()
    if not stmt:
        raise HTTPException(status_code=404, detail="Risk statement not found")

    ctx = _form_context(db, statement=stmt)
    ctx["request"] = request
    return templates.TemplateResponse("risk_library_edit.html", ctx)


@router.post("/risk-library/{statement_id}/edit", response_class=HTMLResponse)
async def risk_library_update(
    request: Request,
    statement_id: int,
    category: str = Form(...),
    trigger_condition: str = Form(...),
    severity: str = Form(...),
    finding_text: str = Form(...),
    remediation_text: str = Form(...),
    is_active: str = Form(None),
    trigger_question_id: str = Form(""),
    trigger_answer_value: str = Form(""),
    db: Session = Depends(get_db),
):
    stmt = db.query(RiskStatement).filter(RiskStatement.id == statement_id).first()
    if not stmt:
        raise HTTPException(status_code=404, detail="Risk statement not found")

    # For QUESTION_ANSWERED, auto-derive category from the selected question
    if trigger_condition == TRIGGER_QUESTION_ANSWERED:
        if not trigger_question_id.strip() or not trigger_answer_value.strip():
            ctx = _form_context(db, statement=stmt, error="Question and answer value are required for question-level triggers.")
            ctx["request"] = request
            return templates.TemplateResponse("risk_library_edit.html", ctx)

        bank_item = db.query(QuestionBankItem).filter(
            QuestionBankItem.id == int(trigger_question_id)
        ).first()
        if bank_item:
            category = bank_item.category

    if not category.strip() or not finding_text.strip() or not remediation_text.strip():
        ctx = _form_context(db, statement=stmt, error="Category, finding text, and remediation text are required.")
        ctx["request"] = request
        return templates.TemplateResponse("risk_library_edit.html", ctx)

    stmt.category = category.strip()
    stmt.trigger_condition = trigger_condition
    stmt.severity = severity
    stmt.finding_text = finding_text.strip()
    stmt.remediation_text = remediation_text.strip()
    stmt.is_active = is_active == "on"

    if trigger_condition == TRIGGER_QUESTION_ANSWERED:
        stmt.trigger_question_id = int(trigger_question_id) if trigger_question_id.strip() else None
        stmt.trigger_answer_value = trigger_answer_value.strip() if trigger_answer_value.strip() else None
    else:
        stmt.trigger_question_id = None
        stmt.trigger_answer_value = None

    db.commit()

    return RedirectResponse(
        url="/risk-library?message=Risk statement updated&message_type=success",
        status_code=303,
    )


@router.post("/risk-library/{statement_id}/delete", response_class=HTMLResponse)
async def risk_library_delete(statement_id: int, db: Session = Depends(get_db)):
    stmt = db.query(RiskStatement).filter(RiskStatement.id == statement_id).first()
    if not stmt:
        raise HTTPException(status_code=404, detail="Risk statement not found")

    db.delete(stmt)
    db.commit()

    return RedirectResponse(
        url="/risk-library?message=Risk statement deleted&message_type=success",
        status_code=303,
    )
