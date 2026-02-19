from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
import json

from app import templates
from models import get_db, QuestionBankItem, User, get_answer_options, has_custom_answer_options
from app.services.auth_service import require_login, require_role

router = APIRouter()

_analyst_dep = require_role("admin", "analyst")


@router.get("/question-bank", response_class=HTMLResponse)
async def question_bank_list(request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_login)):
    items = db.query(QuestionBankItem).order_by(
        QuestionBankItem.category, QuestionBankItem.id
    ).all()

    grouped = {}
    for item in items:
        if item.category not in grouped:
            grouped[item.category] = []
        grouped[item.category].append(item)

    message = request.query_params.get("message")
    message_type = request.query_params.get("message_type", "info")

    return templates.TemplateResponse("question_bank.html", {
        "request": request,
        "grouped": grouped,
        "total_count": len(items),
        "get_answer_options": get_answer_options,
        "has_custom_answer_options": has_custom_answer_options,
        "message": message,
        "message_type": message_type,
    })


@router.get("/question-bank/new", response_class=HTMLResponse)
async def question_bank_new(request: Request, db: Session = Depends(get_db), current_user: User = Depends(_analyst_dep)):
    categories = _get_categories(db)
    return templates.TemplateResponse("question_bank_edit.html", {
        "request": request,
        "item": None,
        "categories": categories,
    })


@router.post("/question-bank/new", response_class=HTMLResponse)
async def question_bank_create(
    request: Request,
    category: str = Form(...),
    text: str = Form(...),
    answer_type: str = Form("standard"),
    custom_options: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    category = category.strip()
    text = text.strip()

    if not category or not text:
        categories = _get_categories(db)
        return templates.TemplateResponse("question_bank_edit.html", {
            "request": request,
            "item": None,
            "categories": categories,
            "error": "Category and question text are required.",
        })

    answer_options = None
    if answer_type == "custom" and custom_options.strip():
        options = [line.strip() for line in custom_options.strip().split('\n') if line.strip()]
        if len(options) >= 2:
            answer_options = json.dumps(options)

    item = QuestionBankItem(
        category=category,
        text=text,
        is_active=True,
        answer_options=answer_options,
    )
    db.add(item)
    db.commit()

    return RedirectResponse(
        url="/question-bank?message=Question created&message_type=success",
        status_code=303,
    )


@router.get("/question-bank/{item_id}/edit", response_class=HTMLResponse)
async def question_bank_edit(request: Request, item_id: int, db: Session = Depends(get_db), current_user: User = Depends(_analyst_dep)):
    item = db.query(QuestionBankItem).filter(QuestionBankItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Question not found")

    categories = _get_categories(db)
    return templates.TemplateResponse("question_bank_edit.html", {
        "request": request,
        "item": item,
        "categories": categories,
        "get_answer_options": get_answer_options,
        "has_custom_answer_options": has_custom_answer_options,
    })


@router.post("/question-bank/{item_id}/edit", response_class=HTMLResponse)
async def question_bank_update(
    request: Request,
    item_id: int,
    category: str = Form(...),
    text: str = Form(...),
    answer_type: str = Form("standard"),
    custom_options: str = Form(""),
    is_active: str = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(_analyst_dep),
):
    item = db.query(QuestionBankItem).filter(QuestionBankItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Question not found")

    category = category.strip()
    text = text.strip()

    if not category or not text:
        categories = _get_categories(db)
        return templates.TemplateResponse("question_bank_edit.html", {
            "request": request,
            "item": item,
            "categories": categories,
            "get_answer_options": get_answer_options,
            "has_custom_answer_options": has_custom_answer_options,
            "error": "Category and question text are required.",
        })

    item.category = category
    item.text = text
    item.is_active = is_active == "on"

    if answer_type == "custom" and custom_options.strip():
        options = [line.strip() for line in custom_options.strip().split('\n') if line.strip()]
        if len(options) >= 2:
            item.answer_options = json.dumps(options)
        else:
            item.answer_options = None
    else:
        item.answer_options = None

    db.commit()

    return RedirectResponse(
        url="/question-bank?message=Question updated&message_type=success",
        status_code=303,
    )


@router.post("/question-bank/{item_id}/toggle")
async def question_bank_toggle(item_id: int, db: Session = Depends(get_db), current_user: User = Depends(_analyst_dep)):
    item = db.query(QuestionBankItem).filter(QuestionBankItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Question not found")

    item.is_active = not item.is_active
    db.commit()

    status = "activated" if item.is_active else "deactivated"
    return RedirectResponse(
        url=f"/question-bank?message=Question {status}&message_type=success",
        status_code=303,
    )


def _get_categories(db: Session) -> list[str]:
    rows = db.query(QuestionBankItem.category).distinct().order_by(QuestionBankItem.category).all()
    return [r[0] for r in rows]
