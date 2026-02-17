from sqlalchemy.orm import Session
from models import (
    RiskStatement,
    TRIGGER_CATEGORY_HAS_DNM, TRIGGER_PARTIAL_HIGH_CRITICAL, TRIGGER_CATEGORY_SCORE_BELOW_50,
    EVAL_DOES_NOT_MEET, EVAL_PARTIAL,
    WEIGHT_HIGH, WEIGHT_CRITICAL,
)

SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}


def match_risk_statements(db: Session, scores: dict) -> list[dict]:
    """Match active risk statements against computed assessment scores.

    Takes the dict returned by compute_assessment_scores(). Returns a list of
    matched risk statement dicts sorted by severity (CRITICAL first).
    """
    # Build sets of (category, trigger_condition) pairs that fired
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

    if not triggered:
        return []

    # Query active risk statements for triggered categories
    triggered_categories = list({cat for cat, _ in triggered})
    statements = db.query(RiskStatement).filter(
        RiskStatement.is_active == True,
        RiskStatement.category.in_(triggered_categories),
    ).all()

    # Filter to only those whose (category, trigger_condition) actually fired
    matched = []
    for stmt in statements:
        if (stmt.category, stmt.trigger_condition) in triggered:
            matched.append({
                "id": stmt.id,
                "category": stmt.category,
                "trigger_condition": stmt.trigger_condition,
                "severity": stmt.severity,
                "finding_text": stmt.finding_text,
                "remediation_text": stmt.remediation_text,
            })

    matched.sort(key=lambda s: SEVERITY_ORDER.get(s["severity"], 99))
    return matched
