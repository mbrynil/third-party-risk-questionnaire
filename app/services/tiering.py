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


def compute_inherent_risk_tier(data_classification: str | None, business_criticality: str | None, access_level: str | None) -> str:
    """Compute inherent risk tier from classification fields.

    Rules:
    - Restricted data OR Critical business -> Tier 1
    - Confidential data OR High business OR Extensive access -> Tier 2
    - Otherwise -> Tier 3
    """
    dc = (data_classification or "").strip()
    bc = (business_criticality or "").strip()
    al = (access_level or "").strip()

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
