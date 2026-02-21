"""Policy dashboard aggregations — KPIs, status breakdown, domain coverage, review calendar."""

from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from models import (
    Policy, PolicyAcknowledgment, User,
    POLICY_STATUS_DRAFT, POLICY_STATUS_UNDER_REVIEW, POLICY_STATUS_APPROVED, POLICY_STATUS_RETIRED,
    VALID_POLICY_STATUSES, POLICY_STATUS_LABELS, POLICY_STATUS_COLORS,
    VALID_POLICY_TYPES, POLICY_TYPE_LABELS,
)


def get_policy_dashboard_data(db: Session) -> dict:
    policies = db.query(Policy).filter(Policy.is_active == True).all()
    total = len(policies)

    # By status
    by_status = {}
    for s in VALID_POLICY_STATUSES:
        by_status[s] = sum(1 for p in policies if p.status == s)

    # By type
    by_type = {}
    for t in VALID_POLICY_TYPES:
        by_type[t] = sum(1 for p in policies if p.policy_type == t)

    # By domain
    by_domain = {}
    for p in policies:
        d = p.domain or "Uncategorized"
        by_domain[d] = by_domain.get(d, 0) + 1

    # Reviews due (next 30 days)
    cutoff = datetime.utcnow() + timedelta(days=30)
    reviews_due = [p for p in policies if p.status == POLICY_STATUS_APPROVED and p.next_review_date and p.next_review_date <= cutoff]
    overdue = [p for p in policies if p.status == POLICY_STATUS_APPROVED and p.next_review_date and p.next_review_date <= datetime.utcnow()]

    # Acknowledgment stats
    approved_policies = [p for p in policies if p.status == POLICY_STATUS_APPROVED]
    total_users = db.query(User).filter(User.is_active == True).count()
    total_acks_needed = len(approved_policies) * total_users if total_users > 0 else 0
    total_acks_done = db.query(PolicyAcknowledgment).count()
    ack_rate = round(total_acks_done / total_acks_needed * 100) if total_acks_needed > 0 else 0

    return {
        "total": total,
        "by_status": by_status,
        "by_type": by_type,
        "by_domain": by_domain,
        "reviews_due": reviews_due,
        "overdue": overdue,
        "ack_rate": ack_rate,
        "total_acks_needed": total_acks_needed,
        "total_acks_done": total_acks_done,
        "status_labels": POLICY_STATUS_LABELS,
        "status_colors": POLICY_STATUS_COLORS,
        "type_labels": POLICY_TYPE_LABELS,
    }
