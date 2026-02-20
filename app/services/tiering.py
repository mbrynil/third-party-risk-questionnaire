"""Inherent risk tiering service.

Computes an inherent risk tier (Tier 1/2/3) from vendor classification fields.
Supports manual override.
"""


TIER_COLORS = {
    "Tier 1": "#dc3545",
    "Tier 2": "#fd7e14",
    "Tier 3": "#198754",
}

TIER_LABELS = {
    "Tier 1": "Critical Risk",
    "Tier 2": "Elevated Risk",
    "Tier 3": "Standard Risk",
}


def compute_inherent_risk_tier(data_classification: str | None, business_criticality: str | None, access_level: str | None, rules=None) -> str:
    """Compute inherent risk tier from classification fields.

    If rules (list of TieringRule) are passed, use them; otherwise use hardcoded defaults.
    Rules are checked in priority order (lower priority number first).
    """
    dc = (data_classification or "").strip()
    bc = (business_criticality or "").strip()
    al = (access_level or "").strip()

    field_values = {
        "data_classification": dc,
        "business_criticality": bc,
        "access_level": al,
    }

    if rules:
        sorted_rules = sorted(rules, key=lambda r: r.priority)
        for rule in sorted_rules:
            actual = field_values.get(rule.field, "")
            if actual and actual == rule.value:
                return rule.tier

    # Fallback defaults if no rules or no match
    if dc == "Restricted" or bc == "Critical":
        return "Tier 1"
    if dc == "Confidential" or bc == "High" or al == "Extensive":
        return "Tier 2"
    return "Tier 3"


def get_effective_tier(vendor) -> str | None:
    """Return the effective tier: override if set, else auto-calculated."""
    if vendor.tier_override:
        return vendor.tier_override
    return vendor.inherent_risk_tier
