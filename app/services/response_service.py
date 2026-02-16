from datetime import datetime
from sqlalchemy.orm import Session
from models import (
    Question, Response, Answer,
    VALID_CHOICES, RESPONSE_STATUS_DRAFT, RESPONSE_STATUS_SUBMITTED,
)


def validate_answers(questions: list, form_data, action: str) -> list[str]:
    """Validate that all questions are answered on submit. Returns list of error messages."""
    if action != "submit":
        return []

    missing = []
    for question in questions:
        if question.answer_mode == "MULTI":
            multi_key = f"multi_{question.id}[]"
            multi_values = form_data.getlist(multi_key)
            if not multi_values:
                missing.append(question)
        else:
            choice_key = f"choice_{question.id}"
            choice_value = form_data.get(choice_key, "")
            if not choice_value or choice_value not in VALID_CHOICES:
                missing.append(question)

    if missing:
        return [f"Please answer all questions before submitting. {len(missing)} unanswered."]
    return []


def save_or_update_response(
    db: Session,
    assessment_id: int,
    vendor_name: str,
    vendor_email: str,
    action: str,
    questions: list,
    form_data,
    existing_response: Response | None = None,
) -> Response:
    """Create or update a response with answers from form data."""
    if existing_response:
        response = existing_response
        response.vendor_name = vendor_name
        response.last_saved_at = datetime.utcnow()
        if action == "submit":
            response.status = RESPONSE_STATUS_SUBMITTED
            response.submitted_at = datetime.utcnow()
        db.query(Answer).filter(Answer.response_id == response.id).delete()
    else:
        response = Response(
            assessment_id=assessment_id,
            vendor_name=vendor_name,
            vendor_email=vendor_email,
            status=RESPONSE_STATUS_SUBMITTED if action == "submit" else RESPONSE_STATUS_DRAFT,
        )
        db.add(response)
        db.flush()

    for question in questions:
        notes_key = f"notes_{question.id}"
        notes_value = str(form_data.get(notes_key, "")).strip() or None

        if question.answer_mode == "MULTI":
            multi_key = f"multi_{question.id}[]"
            multi_values = form_data.getlist(multi_key)
            valid_multi = [v for v in multi_values if v in VALID_CHOICES]
            choice_value = ",".join(valid_multi) if valid_multi else None
        else:
            choice_key = f"choice_{question.id}"
            choice_value = form_data.get(choice_key, "") or None
            choice_value = choice_value if choice_value in VALID_CHOICES else None

        answer = Answer(
            response_id=response.id,
            question_id=question.id,
            answer_choice=choice_value,
            notes=notes_value,
        )
        db.add(answer)

    return response
