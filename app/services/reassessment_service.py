"""Reassessment scheduling service.

Provides tier-based review date suggestions, assessment cloning for reassessment,
and delta computation between current and previous scores.
"""

from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from models import Assessment, ASSESSMENT_STATUS_DRAFT
from app.services.token import generate_unique_token
from app.services.cloning import clone_template_to_assessment


# Tier-based review intervals (months)
TIER_REVIEW_MONTHS = {
    "Tier 1": 12,
    "Tier 2": 18,
    "Tier 3": 24,
}


def suggest_next_review_date(tier: str | None, finalized_at: datetime | None) -> datetime | None:
    """Suggest the next review date based on vendor tier and finalization date."""
    if not tier or not finalized_at:
        return None
    months = TIER_REVIEW_MONTHS.get(tier, 24)
    return finalized_at + timedelta(days=months * 30)


def create_reassessment(db: Session, vendor_id: int, previous_assessment_id: int) -> Assessment | None:
    """Clone a previous assessment to create a new reassessment DRAFT.

    Copies all questions and conditional rules from the previous assessment.
    Returns the new Assessment or None if the previous one doesn't exist.
    """
    prev = db.query(Assessment).filter(Assessment.id == previous_assessment_id).first()
    if not prev:
        return None

    token = generate_unique_token(db)

    new_assessment = Assessment(
        company_name=prev.company_name,
        title=f"Reassessment: {prev.title}",
        token=token,
        vendor_id=vendor_id,
        template_id=prev.template_id,
        status=ASSESSMENT_STATUS_DRAFT,
        previous_assessment_id=previous_assessment_id,
    )
    db.add(new_assessment)
    db.flush()

    # Clone questions + rules from previous assessment
    clone_assessment_to_assessment(db, previous_assessment_id, new_assessment.id)

    return new_assessment


def clone_assessment_to_assessment(db: Session, source_id: int, target_id: int) -> dict:
    """Clone questions and conditional rules from one assessment to another.

    Follows the same pattern as clone_template_to_assessment.
    """
    from models import Question, ConditionalRule

    question_id_map = {}
    source_questions = db.query(Question).filter(
        Question.assessment_id == source_id
    ).order_by(Question.order).all()

    for sq in source_questions:
        new_q = Question(
            assessment_id=target_id,
            question_text=sq.question_text,
            order=sq.order,
            weight=sq.weight,
            expected_operator=sq.expected_operator,
            expected_value=sq.expected_value,
            expected_values=sq.expected_values,
            expected_value_type=sq.expected_value_type,
            answer_mode=sq.answer_mode,
            category=sq.category,
            question_bank_item_id=sq.question_bank_item_id,
            answer_options=sq.answer_options,
        )
        db.add(new_q)
        db.flush()
        question_id_map[sq.id] = new_q.id

    source_rules = db.query(ConditionalRule).filter(
        ConditionalRule.assessment_id == source_id
    ).all()

    for rule in source_rules:
        new_trigger = question_id_map.get(rule.trigger_question_id)
        new_target = question_id_map.get(rule.target_question_id)
        if new_trigger and new_target:
            new_rule = ConditionalRule(
                assessment_id=target_id,
                trigger_question_id=new_trigger,
                operator=rule.operator,
                trigger_values=rule.trigger_values,
                target_question_id=new_target,
                make_required=rule.make_required,
            )
            db.add(new_rule)

    return question_id_map


def compute_assessment_delta(current_scores: dict, previous_scores: dict) -> dict:
    """Compute delta between current and previous assessment scores.

    Returns:
        overall_delta: float (current - previous)
        category_deltas: list of {category, current_score, previous_score, delta}
        new_flagged: list of flagged items in current but not in previous
        resolved_flagged: list of flagged items in previous but not in current
    """
    current_overall = current_scores.get("overall_score")
    previous_overall = previous_scores.get("overall_score")

    overall_delta = None
    if current_overall is not None and previous_overall is not None:
        overall_delta = round(current_overall - previous_overall, 1)

    # Category deltas
    prev_cat_map = {}
    for cat in previous_scores.get("category_scores", []):
        prev_cat_map[cat["category"]] = cat.get("score", 0)

    curr_cat_map = {}
    for cat in current_scores.get("category_scores", []):
        curr_cat_map[cat["category"]] = cat.get("score", 0)

    all_categories = sorted(set(list(prev_cat_map.keys()) + list(curr_cat_map.keys())))
    category_deltas = []
    for cat in all_categories:
        curr = curr_cat_map.get(cat)
        prev = prev_cat_map.get(cat)
        delta = None
        if curr is not None and prev is not None:
            delta = round(curr - prev, 1)
        category_deltas.append({
            "category": cat,
            "current_score": curr,
            "previous_score": prev,
            "delta": delta,
        })

    # Flagged items comparison
    def _flagged_key(item):
        return (item.get("question_text", ""), item.get("category", ""))

    curr_flagged = {_flagged_key(f) for f in current_scores.get("flagged_items", [])}
    prev_flagged = {_flagged_key(f) for f in previous_scores.get("flagged_items", [])}

    new_flagged_keys = curr_flagged - prev_flagged
    resolved_flagged_keys = prev_flagged - curr_flagged

    new_flagged = [f for f in current_scores.get("flagged_items", []) if _flagged_key(f) in new_flagged_keys]
    resolved_flagged = [f for f in previous_scores.get("flagged_items", []) if _flagged_key(f) in resolved_flagged_keys]

    return {
        "overall_delta": overall_delta,
        "current_overall": current_overall,
        "previous_overall": previous_overall,
        "category_deltas": category_deltas,
        "new_flagged": new_flagged,
        "resolved_flagged": resolved_flagged,
        "new_flagged_count": len(new_flagged),
        "resolved_flagged_count": len(resolved_flagged),
    }
