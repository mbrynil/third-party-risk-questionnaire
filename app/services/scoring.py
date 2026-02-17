from models import (
    compute_expectation_status,
    EVAL_MEETS, EVAL_PARTIAL, EVAL_DOES_NOT_MEET, EVAL_NO_EXPECTATION,
    WEIGHT_LOW, WEIGHT_MEDIUM, WEIGHT_HIGH, WEIGHT_CRITICAL,
    RISK_LEVEL_VERY_LOW, RISK_LEVEL_LOW, RISK_LEVEL_MODERATE,
    RISK_LEVEL_HIGH, RISK_LEVEL_VERY_HIGH,
)

WEIGHT_MULTIPLIERS = {
    WEIGHT_LOW: 1,
    WEIGHT_MEDIUM: 2,
    WEIGHT_HIGH: 3,
    WEIGHT_CRITICAL: 5,
}

EVAL_SCORE = {
    EVAL_MEETS: 1.0,
    EVAL_PARTIAL: 0.5,
    EVAL_DOES_NOT_MEET: 0.0,
}


def suggest_risk_level(score: float) -> str:
    """Map a 0-100 score to a risk level string."""
    if score >= 90:
        return RISK_LEVEL_VERY_LOW
    elif score >= 70:
        return RISK_LEVEL_LOW
    elif score >= 50:
        return RISK_LEVEL_MODERATE
    elif score >= 30:
        return RISK_LEVEL_HIGH
    else:
        return RISK_LEVEL_VERY_HIGH


def compute_assessment_scores(questions, response) -> dict:
    """Compute weighted scores, category breakdowns, flagged items, and risk suggestion.

    Returns dict with keys:
        overall_score (float 0-100 or None if no scorable questions)
        category_scores (list of dicts sorted worst-first)
        flagged_items (list of dicts sorted by severity)
        suggested_risk_level (str)
        question_details (list of per-question dicts)
        meets_count, partial_count, does_not_meet_count, no_expectation_count (ints)
    """
    answers_dict = {}
    if response:
        answers_dict = {a.question_id: a for a in response.answers}

    total_earned = 0.0
    total_possible = 0.0
    category_earned = {}
    category_possible = {}
    category_count = {}
    flagged_items = []
    question_details = []

    meets_count = 0
    partial_count = 0
    does_not_meet_count = 0
    no_expectation_count = 0

    for q in questions:
        answer = answers_dict.get(q.id)
        answer_choice = answer.answer_choice if answer else None
        answer_text = answer.answer_text if answer else None

        if response:
            eval_status = compute_expectation_status(
                q.expected_value, answer_choice, q.expected_values, q.answer_mode,
                answer_options=q.answer_options
            )
        else:
            eval_status = EVAL_NO_EXPECTATION

        # Counts
        if eval_status == EVAL_MEETS:
            meets_count += 1
        elif eval_status == EVAL_PARTIAL:
            partial_count += 1
        elif eval_status == EVAL_DOES_NOT_MEET:
            does_not_meet_count += 1
        else:
            no_expectation_count += 1

        multiplier = WEIGHT_MULTIPLIERS.get(q.weight, 2)
        cat = q.category or "Uncategorized"

        detail = {
            "question_id": q.id,
            "question_text": q.question_text,
            "weight": q.weight,
            "category": cat,
            "eval_status": eval_status,
            "answer_choice": answer_choice,
            "answer_text": answer_text,
            "question_bank_item_id": getattr(q, 'question_bank_item_id', None),
        }

        if eval_status != EVAL_NO_EXPECTATION:
            earned = EVAL_SCORE.get(eval_status, 0.0) * multiplier
            possible = multiplier

            total_earned += earned
            total_possible += possible

            category_earned[cat] = category_earned.get(cat, 0.0) + earned
            category_possible[cat] = category_possible.get(cat, 0.0) + possible
            category_count[cat] = category_count.get(cat, 0) + 1

            detail["earned"] = earned
            detail["possible"] = possible

            # Flag problem items
            is_flagged = False
            if eval_status == EVAL_DOES_NOT_MEET:
                is_flagged = True
            elif eval_status == EVAL_PARTIAL and q.weight in (WEIGHT_HIGH, WEIGHT_CRITICAL):
                is_flagged = True

            if is_flagged:
                weight_severity = {WEIGHT_CRITICAL: 0, WEIGHT_HIGH: 1, WEIGHT_MEDIUM: 2, WEIGHT_LOW: 3}
                eval_severity = {EVAL_DOES_NOT_MEET: 0, EVAL_PARTIAL: 1}
                flagged_items.append({
                    **detail,
                    "sort_key": (weight_severity.get(q.weight, 4), eval_severity.get(eval_status, 2)),
                })

        question_details.append(detail)

    # Overall score
    if total_possible > 0:
        overall_score = round((total_earned / total_possible) * 100, 1)
    else:
        overall_score = None

    # Group question details by category
    category_questions = {}
    for detail in question_details:
        cat = detail["category"]
        if cat not in category_questions:
            category_questions[cat] = []
        category_questions[cat].append(detail)

    # Category scores sorted worst-first
    category_scores = []
    for cat in category_earned:
        possible = category_possible[cat]
        if possible > 0:
            score = round((category_earned[cat] / possible) * 100, 1)
        else:
            score = None
        category_scores.append({
            "category": cat,
            "score": score,
            "risk_level": suggest_risk_level(score) if score is not None else None,
            "earned": category_earned[cat],
            "possible": possible,
            "count": category_count.get(cat, 0),
            "questions": category_questions.get(cat, []),
        })
    category_scores.sort(key=lambda c: c["score"] if c["score"] is not None else 999)

    # Sort flagged items by severity
    flagged_items.sort(key=lambda f: f["sort_key"])
    for item in flagged_items:
        del item["sort_key"]

    suggested = suggest_risk_level(overall_score) if overall_score is not None else None

    return {
        "overall_score": overall_score,
        "category_scores": category_scores,
        "flagged_items": flagged_items,
        "suggested_risk_level": suggested,
        "question_details": question_details,
        "meets_count": meets_count,
        "partial_count": partial_count,
        "does_not_meet_count": does_not_meet_count,
        "no_expectation_count": no_expectation_count,
    }
