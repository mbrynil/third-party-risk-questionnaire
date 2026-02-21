"""Policy management service — CRUD, workflow, mappings, acknowledgments."""

from datetime import datetime, timedelta
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from models import (
    Policy, PolicyVersion, PolicyControlMapping, PolicyFrameworkMapping,
    PolicyAcknowledgment, User, Control,
    POLICY_STATUS_DRAFT, POLICY_STATUS_UNDER_REVIEW, POLICY_STATUS_APPROVED, POLICY_STATUS_RETIRED,
    VALID_CONTROL_DOMAINS,
)

DOMAIN_REF_PREFIX = {
    "Access Control": "AC", "Asset Management": "AM", "Business Continuity": "BC",
    "Change Management": "CM", "Cryptography": "CR", "Data Protection": "DP",
    "Governance": "GV", "Human Resources": "HR", "Incident Management": "IR",
    "Network Security": "NS", "Physical Security": "PS", "Risk Management": "RM",
    "Secure Development": "SD", "Security Monitoring": "SM", "Security Operations": "SO",
    "Third-Party Management": "TP", "Training & Awareness": "TA", "Vulnerability Management": "VM",
}


def generate_policy_ref(db: Session, domain: str) -> str:
    prefix = DOMAIN_REF_PREFIX.get(domain, "XX")
    pattern = f"POL-{prefix}-%"
    existing = db.query(Policy.policy_ref).filter(Policy.policy_ref.like(pattern)).all()
    max_num = 0
    for (ref,) in existing:
        try:
            num = int(ref.split("-")[-1])
            if num > max_num:
                max_num = num
        except (ValueError, IndexError):
            pass
    return f"POL-{prefix}-{max_num + 1:03d}"


def get_all_policies(db, active_only=True, status=None, domain=None, policy_type=None, owner_id=None):
    q = db.query(Policy)
    if active_only:
        q = q.filter(Policy.is_active == True)
    if status:
        q = q.filter(Policy.status == status)
    if domain:
        q = q.filter(Policy.domain == domain)
    if policy_type:
        q = q.filter(Policy.policy_type == policy_type)
    if owner_id:
        q = q.filter(Policy.owner_user_id == owner_id)
    return q.order_by(Policy.policy_ref).all()


def get_policy(db, policy_id):
    return db.query(Policy).options(
        joinedload(Policy.owner),
        joinedload(Policy.approver),
        joinedload(Policy.versions),
        joinedload(Policy.control_mappings).joinedload(PolicyControlMapping.control),
        joinedload(Policy.framework_mappings),
        joinedload(Policy.acknowledgments).joinedload(PolicyAcknowledgment.user),
    ).filter(Policy.id == policy_id).first()


def create_policy(db, **kwargs):
    domain = kwargs.get("domain", "Governance")
    policy_ref = generate_policy_ref(db, domain)
    policy = Policy(
        policy_ref=policy_ref,
        title=kwargs.get("title", ""),
        description=kwargs.get("description"),
        content=kwargs.get("content"),
        policy_type=kwargs.get("policy_type", "POLICY"),
        domain=domain,
        category=kwargs.get("category"),
        status=POLICY_STATUS_DRAFT,
        review_frequency_days=kwargs.get("review_frequency_days", 365),
        owner_user_id=kwargs.get("owner_user_id"),
    )
    db.add(policy)
    db.flush()
    return policy


def update_policy(db, policy_id, **kwargs):
    policy = db.query(Policy).filter(Policy.id == policy_id).first()
    if not policy:
        return None
    # If approved and content is changing, create version snapshot first
    if policy.status == POLICY_STATUS_APPROVED and "content" in kwargs and kwargs["content"] != policy.content:
        db.add(PolicyVersion(
            policy_id=policy.id,
            version_number=policy.version,
            title=policy.title,
            content=policy.content,
            change_summary="Auto-saved before edit",
            created_by_user_id=kwargs.get("editor_user_id"),
        ))
        policy.version = (policy.version or 1) + 1
    # Remove non-model keys
    kwargs.pop("editor_user_id", None)
    for k, v in kwargs.items():
        if hasattr(policy, k):
            setattr(policy, k, v)
    db.flush()
    return policy


def delete_policy(db, policy_id):
    policy = db.query(Policy).filter(Policy.id == policy_id).first()
    if not policy:
        return False
    policy.is_active = False
    db.flush()
    return True


def submit_for_review(db, policy_id):
    policy = db.query(Policy).filter(Policy.id == policy_id).first()
    if policy and policy.status == POLICY_STATUS_DRAFT:
        policy.status = POLICY_STATUS_UNDER_REVIEW
        db.flush()
    return policy


def approve_policy(db, policy_id, approver_id):
    policy = db.query(Policy).filter(Policy.id == policy_id).first()
    if policy and policy.status == POLICY_STATUS_UNDER_REVIEW:
        policy.status = POLICY_STATUS_APPROVED
        policy.approver_user_id = approver_id
        policy.approved_at = datetime.utcnow()
        policy.effective_date = datetime.utcnow()
        policy.review_date = datetime.utcnow()
        policy.next_review_date = datetime.utcnow() + timedelta(days=policy.review_frequency_days or 365)
        db.flush()
    return policy


def retire_policy(db, policy_id):
    policy = db.query(Policy).filter(Policy.id == policy_id).first()
    if policy and policy.status == POLICY_STATUS_APPROVED:
        policy.status = POLICY_STATUS_RETIRED
        db.flush()
    return policy


def revert_to_draft(db, policy_id):
    policy = db.query(Policy).filter(Policy.id == policy_id).first()
    if policy:
        policy.status = POLICY_STATUS_DRAFT
        policy.approver_user_id = None
        policy.approved_at = None
        db.flush()
    return policy


def get_version_history(db, policy_id):
    return db.query(PolicyVersion).filter(
        PolicyVersion.policy_id == policy_id
    ).order_by(PolicyVersion.version_number.desc()).all()


def set_control_mappings(db, policy_id, control_ids):
    db.query(PolicyControlMapping).filter(PolicyControlMapping.policy_id == policy_id).delete()
    for cid in control_ids:
        db.add(PolicyControlMapping(policy_id=policy_id, control_id=cid))
    db.flush()


def set_framework_mappings(db, policy_id, mappings):
    """mappings is a list of (framework, requirement_reference) tuples."""
    db.query(PolicyFrameworkMapping).filter(PolicyFrameworkMapping.policy_id == policy_id).delete()
    for fw, ref in mappings:
        if fw and ref:
            db.add(PolicyFrameworkMapping(policy_id=policy_id, framework=fw, requirement_reference=ref))
    db.flush()


def acknowledge_policy(db, policy_id, user_id):
    policy = db.query(Policy).filter(Policy.id == policy_id).first()
    if not policy:
        return None
    ack = db.query(PolicyAcknowledgment).filter(
        PolicyAcknowledgment.policy_id == policy_id,
        PolicyAcknowledgment.user_id == user_id,
    ).first()
    if ack:
        ack.acknowledged_at = datetime.utcnow()
        ack.version_acknowledged = policy.version
    else:
        ack = PolicyAcknowledgment(
            policy_id=policy_id, user_id=user_id,
            version_acknowledged=policy.version,
        )
        db.add(ack)
    db.flush()
    return ack


def get_acknowledgment_status(db, policy_id):
    users = db.query(User).filter(User.is_active == True).all()
    acks = db.query(PolicyAcknowledgment).filter(
        PolicyAcknowledgment.policy_id == policy_id
    ).all()
    ack_map = {a.user_id: a for a in acks}
    result = []
    for u in users:
        a = ack_map.get(u.id)
        result.append({
            "user": u,
            "acknowledged": a is not None,
            "acknowledged_at": a.acknowledged_at if a else None,
            "version": a.version_acknowledged if a else None,
        })
    return result


def get_policies_needing_review(db, days_ahead=30):
    cutoff = datetime.utcnow() + timedelta(days=days_ahead)
    return db.query(Policy).filter(
        Policy.is_active == True,
        Policy.status == POLICY_STATUS_APPROVED,
        Policy.next_review_date != None,
        Policy.next_review_date <= cutoff,
    ).order_by(Policy.next_review_date).all()


def get_policy_stats(db):
    total = db.query(Policy).filter(Policy.is_active == True).count()
    by_status = {}
    for s in [POLICY_STATUS_DRAFT, POLICY_STATUS_UNDER_REVIEW, POLICY_STATUS_APPROVED, POLICY_STATUS_RETIRED]:
        by_status[s] = db.query(Policy).filter(Policy.is_active == True, Policy.status == s).count()
    return {"total": total, "by_status": by_status}
