from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import func

from app import templates
from models import (
    get_db, RiskStatement, QuestionBankItem,
    VALID_TRIGGER_CONDITIONS, VALID_SEVERITIES, TRIGGER_LABELS,
)

router = APIRouter()


def _get_categories(db: Session) -> list[str]:
    """Get distinct categories from the question bank, sorted."""
    rows = db.query(QuestionBankItem.category).distinct().order_by(QuestionBankItem.category).all()
    return [r[0] for r in rows]


@router.get("/risk-library", response_class=HTMLResponse)
async def risk_library_list(request: Request, db: Session = Depends(get_db)):
    statements = db.query(RiskStatement).order_by(RiskStatement.category, RiskStatement.severity).all()

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
    return templates.TemplateResponse("risk_library_edit.html", {
        "request": request,
        "statement": None,
        "categories": _get_categories(db),
        "trigger_conditions": VALID_TRIGGER_CONDITIONS,
        "trigger_labels": TRIGGER_LABELS,
        "severities": VALID_SEVERITIES,
    })


@router.post("/risk-library/new", response_class=HTMLResponse)
async def risk_library_create(
    request: Request,
    category: str = Form(...),
    trigger_condition: str = Form(...),
    severity: str = Form(...),
    finding_text: str = Form(...),
    remediation_text: str = Form(...),
    db: Session = Depends(get_db),
):
    if not category.strip() or not finding_text.strip() or not remediation_text.strip():
        return templates.TemplateResponse("risk_library_edit.html", {
            "request": request,
            "statement": None,
            "categories": _get_categories(db),
            "trigger_conditions": VALID_TRIGGER_CONDITIONS,
            "trigger_labels": TRIGGER_LABELS,
            "severities": VALID_SEVERITIES,
            "error": "Category, finding text, and remediation text are required.",
        })

    stmt = RiskStatement(
        category=category.strip(),
        trigger_condition=trigger_condition,
        severity=severity,
        finding_text=finding_text.strip(),
        remediation_text=remediation_text.strip(),
        is_active=True,
    )
    db.add(stmt)
    db.commit()

    return RedirectResponse(
        url="/risk-library?message=Risk statement created&message_type=success",
        status_code=303,
    )


@router.get("/risk-library/{statement_id}/edit", response_class=HTMLResponse)
async def risk_library_edit(request: Request, statement_id: int, db: Session = Depends(get_db)):
    stmt = db.query(RiskStatement).filter(RiskStatement.id == statement_id).first()
    if not stmt:
        raise HTTPException(status_code=404, detail="Risk statement not found")

    return templates.TemplateResponse("risk_library_edit.html", {
        "request": request,
        "statement": stmt,
        "categories": _get_categories(db),
        "trigger_conditions": VALID_TRIGGER_CONDITIONS,
        "trigger_labels": TRIGGER_LABELS,
        "severities": VALID_SEVERITIES,
    })


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
    db: Session = Depends(get_db),
):
    stmt = db.query(RiskStatement).filter(RiskStatement.id == statement_id).first()
    if not stmt:
        raise HTTPException(status_code=404, detail="Risk statement not found")

    if not category.strip() or not finding_text.strip() or not remediation_text.strip():
        return templates.TemplateResponse("risk_library_edit.html", {
            "request": request,
            "statement": stmt,
            "categories": _get_categories(db),
            "trigger_conditions": VALID_TRIGGER_CONDITIONS,
            "trigger_labels": TRIGGER_LABELS,
            "severities": VALID_SEVERITIES,
            "error": "Category, finding text, and remediation text are required.",
        })

    stmt.category = category.strip()
    stmt.trigger_condition = trigger_condition
    stmt.severity = severity
    stmt.finding_text = finding_text.strip()
    stmt.remediation_text = remediation_text.strip()
    stmt.is_active = is_active == "on"
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
