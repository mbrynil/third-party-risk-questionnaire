from sqlalchemy.orm import Session, joinedload
from models import (
    RiskStatement, QuestionBankItem,
    TRIGGER_CATEGORY_HAS_DNM, TRIGGER_PARTIAL_HIGH_CRITICAL, TRIGGER_CATEGORY_SCORE_BELOW_50,
    TRIGGER_QUESTION_ANSWERED,
    EVAL_DOES_NOT_MEET, EVAL_PARTIAL,
    WEIGHT_HIGH, WEIGHT_CRITICAL,
)

SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}


def match_risk_statements(db: Session, scores: dict) -> list[dict]:
    """Match active risk statements against computed assessment scores.

    Takes the dict returned by compute_assessment_scores(). Returns a list of
    matched risk statement dicts sorted by severity (CRITICAL first).
    """
    matched = []

    # ===== Category-level matching (existing logic) =====
    triggered = set()

    for item in scores.get("flagged_items", []):
        cat = item.get("category", "Uncategorized")
        if item.get("eval_status") == EVAL_DOES_NOT_MEET:
            triggered.add((cat, TRIGGER_CATEGORY_HAS_DNM))
        if item.get("eval_status") == EVAL_PARTIAL and item.get("weight") in (WEIGHT_HIGH, WEIGHT_CRITICAL):
            triggered.add((cat, TRIGGER_PARTIAL_HIGH_CRITICAL))

    for cat_score in scores.get("category_scores", []):
        cat = cat_score.get("category", "Uncategorized")
        score = cat_score.get("score")
        if score is not None and score < 50:
            triggered.add((cat, TRIGGER_CATEGORY_SCORE_BELOW_50))

    if triggered:
        triggered_categories = list({cat for cat, _ in triggered})
        statements = db.query(RiskStatement).filter(
            RiskStatement.is_active == True,
            RiskStatement.category.in_(triggered_categories),
            RiskStatement.trigger_condition != TRIGGER_QUESTION_ANSWERED,
        ).all()

        for stmt in statements:
            if (stmt.category, stmt.trigger_condition) in triggered:
                matched.append({
                    "id": stmt.id,
                    "category": stmt.category,
                    "trigger_condition": stmt.trigger_condition,
                    "severity": stmt.severity,
                    "finding_text": stmt.finding_text,
                    "remediation_text": stmt.remediation_text,
                    "trigger_question_text": None,
                    "trigger_answer_value": None,
                })

    # ===== Question-level matching (new) =====
    # Build map: question_bank_item_id -> answer_choice
    answer_map = {}
    for detail in scores.get("question_details", []):
        bank_id = detail.get("question_bank_item_id")
        answer = detail.get("answer_choice")
        if bank_id and answer:
            answer_map[bank_id] = answer

    if answer_map:
        q_statements = db.query(RiskStatement).options(
            joinedload(RiskStatement.trigger_question)
        ).filter(
            RiskStatement.is_active == True,
            RiskStatement.trigger_condition == TRIGGER_QUESTION_ANSWERED,
            RiskStatement.trigger_question_id.in_(list(answer_map.keys())),
        ).all()

        for stmt in q_statements:
            actual_answer = answer_map.get(stmt.trigger_question_id, "")
            if actual_answer.lower() == (stmt.trigger_answer_value or "").lower():
                q_text = stmt.trigger_question.text if stmt.trigger_question else "Unknown question"
                matched.append({
                    "id": stmt.id,
                    "category": stmt.category,
                    "trigger_condition": stmt.trigger_condition,
                    "severity": stmt.severity,
                    "finding_text": stmt.finding_text,
                    "remediation_text": stmt.remediation_text,
                    "trigger_question_text": q_text,
                    "trigger_answer_value": stmt.trigger_answer_value,
                })

    matched.sort(key=lambda s: SEVERITY_ORDER.get(s["severity"], 99))
    return matched
