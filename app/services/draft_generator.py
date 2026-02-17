from models import (
    RISK_LEVEL_VERY_HIGH, RISK_LEVEL_HIGH, RISK_LEVEL_MODERATE,
    DECISION_REJECT, DECISION_NEEDS_FOLLOW_UP,
    DECISION_APPROVE_WITH_CONDITIONS, DECISION_APPROVE,
    WEIGHT_CRITICAL, WEIGHT_HIGH,
)

RISK_TO_OUTCOME = {
    RISK_LEVEL_VERY_HIGH: DECISION_REJECT,
    RISK_LEVEL_HIGH: DECISION_NEEDS_FOLLOW_UP,
    RISK_LEVEL_MODERATE: DECISION_APPROVE_WITH_CONDITIONS,
}


def generate_draft(scores: dict, risk_suggestions: list[dict]) -> dict:
    """Build auto-filled decision fields from scores and risk suggestions.

    Returns dict with keys: overall_risk_rating, decision_outcome,
    key_findings, remediation_required, rationale.
    """
    overall_score = scores.get("overall_score")
    suggested_risk = scores.get("suggested_risk_level")
    category_scores = scores.get("category_scores", [])
    flagged_items = scores.get("flagged_items", [])
    meets_count = scores.get("meets_count", 0)
    partial_count = scores.get("partial_count", 0)
    does_not_meet_count = scores.get("does_not_meet_count", 0)

    # --- Overall risk rating ---
    overall_risk_rating = suggested_risk

    # --- Decision outcome ---
    decision_outcome = RISK_TO_OUTCOME.get(suggested_risk, DECISION_APPROVE)

    # --- Key findings ---
    findings_parts = []

    if overall_score is not None:
        risk_label = suggested_risk.replace("_", " ").title() if suggested_risk else "Unknown"
        findings_parts.append(f"Assessment scored {overall_score}/100 — {risk_label} risk.")

    weak_categories = [c for c in category_scores if c.get("score") is not None and c["score"] < 70]
    if weak_categories:
        findings_parts.append("")
        findings_parts.append("Underperforming categories:")
        for cat in weak_categories:
            risk_label = cat["risk_level"].replace("_", " ").title() if cat.get("risk_level") else ""
            findings_parts.append(f"- {cat['category']}: {cat['score']}% ({risk_label} Risk) — {cat['count']} questions")

    if risk_suggestions:
        findings_parts.append("")
        findings_parts.append("Risk statement findings:")
        for s in risk_suggestions:
            findings_parts.append(f"[{s['category']}] {s['finding_text']}")

    suggestion_categories = {s["category"] for s in risk_suggestions} if risk_suggestions else set()
    uncovered_flagged = [f for f in flagged_items if f.get("category") not in suggestion_categories]
    if uncovered_flagged and not risk_suggestions:
        critical_count = sum(1 for f in flagged_items if f.get("weight") == WEIGHT_CRITICAL)
        high_count = sum(1 for f in flagged_items if f.get("weight") == WEIGHT_HIGH)
        findings_parts.append("")
        findings_parts.append(f"{len(flagged_items)} flagged items identified ({critical_count} critical, {high_count} high weight).")

    key_findings = "\n".join(findings_parts) if findings_parts else None

    # --- Remediation required ---
    remediation_parts = []
    if risk_suggestions:
        for s in risk_suggestions:
            remediation_parts.append(f"[{s['category']}] {s['remediation_text']}")
    elif flagged_items:
        remediation_parts.append("Review flagged items and determine remediation actions.")

    remediation_required = "\n\n".join(remediation_parts) if remediation_parts else None

    # --- Rationale ---
    rationale_parts = []
    if overall_score is not None:
        rationale_parts.append(
            f"Vendor scored {overall_score}/100 overall. "
            f"{meets_count} questions met expectations, "
            f"{partial_count} partially met, "
            f"{does_not_meet_count} did not meet."
        )

    if weak_categories:
        cat_names = ", ".join(c["category"] for c in weak_categories)
        rationale_parts.append(f"Areas of concern: {cat_names}.")

    outcome_label = decision_outcome.replace("_", " ").title() if decision_outcome else "Unknown"
    rationale_parts.append(f"Based on the assessment results, the recommended outcome is {outcome_label}.")

    rationale = " ".join(rationale_parts) if rationale_parts else None

    return {
        "overall_risk_rating": overall_risk_rating,
        "decision_outcome": decision_outcome,
        "key_findings": key_findings,
        "remediation_required": remediation_required,
        "rationale": rationale,
    }
