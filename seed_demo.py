"""One-time script to populate the database with 10 demo vendors and realistic assessment data."""
import random
import json
from datetime import datetime, timedelta

from models import (
    SessionLocal, Vendor, Assessment, Question, Response, Answer,
    AssessmentDecision, QuestionBankItem,
    VENDOR_STATUS_ACTIVE, VENDOR_STATUS_ARCHIVED,
    ASSESSMENT_STATUS_DRAFT, ASSESSMENT_STATUS_SENT,
    ASSESSMENT_STATUS_IN_PROGRESS, ASSESSMENT_STATUS_SUBMITTED,
    ASSESSMENT_STATUS_REVIEWED,
    RESPONSE_STATUS_SUBMITTED,
    DECISION_STATUS_FINAL, DECISION_STATUS_DRAFT,
    WEIGHT_LOW, WEIGHT_MEDIUM, WEIGHT_HIGH, WEIGHT_CRITICAL,
    RISK_LEVEL_VERY_LOW, RISK_LEVEL_LOW, RISK_LEVEL_MODERATE,
    RISK_LEVEL_HIGH, RISK_LEVEL_VERY_HIGH,
    DECISION_APPROVE, DECISION_APPROVE_WITH_CONDITIONS,
    DECISION_NEEDS_FOLLOW_UP, DECISION_REJECT,
)
from app.services.scoring import compute_assessment_scores, suggest_risk_level
from app.services.token import generate_unique_token

random.seed(42)

VENDORS = [
    ("CloudSecure Inc.", "Sarah Chen", "sarah@cloudsecure.io"),
    ("DataVault Systems", "James Rivera", "james@datavault.com"),
    ("NexGen Analytics", "Priya Patel", "priya@nexgenanalytics.com"),
    ("TrustBridge Solutions", "Michael Okafor", "michael@trustbridge.io"),
    ("CyberShield Corp", "Emma Johansson", "emma@cybershield.com"),
    ("Apex Cloud Services", "David Kim", "david@apexcloud.io"),
    ("Sentinel Data Labs", "Rachel Thompson", "rachel@sentineldata.com"),
    ("Fortify Networks", "Carlos Mendez", "carlos@fortifynet.com"),
    ("Ironclad Security", "Lisa Wang", "lisa@ironcladSec.com"),
    ("Quantum Safe Inc.", "Alex Petrov", "alex@quantumsafe.io"),
]

WEIGHT_DIST = [WEIGHT_LOW] * 1 + [WEIGHT_MEDIUM] * 5 + [WEIGHT_HIGH] * 3 + [WEIGHT_CRITICAL] * 1

# Profiles: (answer distribution, question count range, assessment title pattern)
VENDOR_PROFILES = [
    # Great vendors
    {"bias": {"yes": 0.80, "partial": 0.12, "no": 0.05, "na": 0.03}, "q_range": (20, 35), "quality": "great"},
    {"bias": {"yes": 0.85, "partial": 0.10, "no": 0.03, "na": 0.02}, "q_range": (15, 25), "quality": "great"},
    # Good vendors
    {"bias": {"yes": 0.65, "partial": 0.20, "no": 0.10, "na": 0.05}, "q_range": (18, 30), "quality": "good"},
    {"bias": {"yes": 0.70, "partial": 0.15, "no": 0.10, "na": 0.05}, "q_range": (12, 20), "quality": "good"},
    # Mediocre vendors
    {"bias": {"yes": 0.45, "partial": 0.25, "no": 0.20, "na": 0.10}, "q_range": (20, 40), "quality": "mediocre"},
    {"bias": {"yes": 0.50, "partial": 0.20, "no": 0.25, "na": 0.05}, "q_range": (15, 25), "quality": "mediocre"},
    # Poor vendors
    {"bias": {"yes": 0.30, "partial": 0.20, "no": 0.40, "na": 0.10}, "q_range": (10, 20), "quality": "poor"},
    {"bias": {"yes": 0.25, "partial": 0.15, "no": 0.50, "na": 0.10}, "q_range": (25, 40), "quality": "poor"},
    # Mixed
    {"bias": {"yes": 0.55, "partial": 0.25, "no": 0.15, "na": 0.05}, "q_range": (18, 28), "quality": "mixed"},
    {"bias": {"yes": 0.60, "partial": 0.18, "no": 0.17, "na": 0.05}, "q_range": (10, 18), "quality": "mixed"},
]

SENSITIVITY_OPTIONS = ["LOW", "MEDIUM", "HIGH", "VERY_HIGH"]
CRITICALITY_OPTIONS = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]

TITLES = [
    "Annual Security Review 2025",
    "Q4 2025 Vendor Assessment",
    "Initial Onboarding Assessment",
    "Renewal Security Assessment",
    "Comprehensive Risk Evaluation",
    "Data Protection Assessment",
    "Cloud Security Review",
    "SOC2 Compliance Check",
    "Periodic Risk Review",
    "Enhanced Due Diligence",
]

RATIONALE_TEMPLATES = {
    "great": [
        "Vendor demonstrates mature security practices across all assessed domains. Strong controls in access management, encryption, and incident response. Minimal gaps identified.",
        "Comprehensive security program with well-documented policies. SOC 2 Type II certified with no material exceptions. Recommend continued engagement.",
    ],
    "good": [
        "Vendor meets most security requirements with minor gaps in documentation and monitoring. Recommend approval with periodic review to track improvements.",
        "Overall solid security posture. Some areas require attention, particularly around vulnerability management cadence and log forwarding capabilities.",
    ],
    "mediocre": [
        "Vendor demonstrates inconsistent security practices. While some controls are in place, significant gaps exist in encryption key management and incident response procedures.",
        "Mixed results across assessment categories. Access controls are adequate but continuous monitoring and BC/DR capabilities require substantial improvement.",
    ],
    "poor": [
        "Vendor fails to meet minimum security requirements in multiple critical areas. Systemic deficiencies in access control, encryption, and incident response noted.",
        "Assessment reveals fundamental gaps in the vendor's security program. Lack of documented policies, inadequate monitoring, and missing certifications present unacceptable risk.",
    ],
    "mixed": [
        "Vendor shows strong capabilities in some areas but notable weaknesses in others. Encryption and access control are solid, but incident response and vendor management need work.",
        "Security posture varies significantly across domains. Recommend conditional approval with specific remediation requirements and accelerated review timeline.",
    ],
}

FINDINGS_TEMPLATES = {
    "great": "No critical findings. Minor recommendations for enhanced log retention and expanded MFA coverage to non-privileged accounts.",
    "good": "2 moderate findings: (1) Vulnerability scan cadence should increase to monthly, (2) DR testing documentation needs updating.",
    "mediocre": "5 findings identified: (1) No formal incident response plan, (2) Encryption key rotation not defined, (3) Access reviews not conducted annually, (4) Missing SOC 2 certification, (5) Backup encryption not confirmed.",
    "poor": "8 critical findings across access control, encryption, incident response, and compliance. Vendor lacks fundamental security controls expected for data processing.",
    "mixed": "3 findings: (1) Continuous monitoring gaps in application-level logging, (2) Third-party vendor management program immature, (3) BC/DR testing not conducted in past 12 months.",
}

REMEDIATION_TEMPLATES = {
    "great": "No mandatory remediation. Recommend MFA expansion as enhancement.",
    "good": "1. Increase vulnerability scanning to monthly cadence within 60 days.\n2. Update DR test documentation and conduct annual test within 90 days.",
    "mediocre": "1. Develop and submit incident response plan within 45 days.\n2. Implement encryption key rotation policy within 60 days.\n3. Conduct user access review within 30 days.\n4. Provide SOC 2 audit timeline within 30 days.\n5. Confirm backup encryption within 15 days.",
    "poor": "Comprehensive remediation plan required within 30 days addressing all 8 critical findings. Vendor engagement suspended pending submission and acceptance of remediation plan.",
    "mixed": "1. Implement application-level audit logging within 60 days.\n2. Establish third-party risk management program within 90 days.\n3. Conduct BC/DR test and submit results within 60 days.",
}


def pick_answer(bias):
    choices = list(bias.keys())
    weights = list(bias.values())
    return random.choices(choices, weights=weights, k=1)[0]


def risk_to_outcome(risk_level):
    mapping = {
        RISK_LEVEL_VERY_LOW: DECISION_APPROVE,
        RISK_LEVEL_LOW: DECISION_APPROVE,
        RISK_LEVEL_MODERATE: DECISION_APPROVE_WITH_CONDITIONS,
        RISK_LEVEL_HIGH: DECISION_NEEDS_FOLLOW_UP,
        RISK_LEVEL_VERY_HIGH: DECISION_REJECT,
    }
    return mapping.get(risk_level, DECISION_APPROVE_WITH_CONDITIONS)


def main():
    db = SessionLocal()
    try:
        # Get all active question bank items grouped by category
        bank_items = db.query(QuestionBankItem).filter(
            QuestionBankItem.is_active == True
        ).order_by(QuestionBankItem.category, QuestionBankItem.id).all()

        if not bank_items:
            print("ERROR: No question bank items found. Run the app first to seed them.")
            return

        categories = {}
        for item in bank_items:
            categories.setdefault(item.category, []).append(item)

        cat_names = list(categories.keys())
        print(f"Found {len(bank_items)} bank items across {len(cat_names)} categories")

        created_vendors = 0
        created_assessments = 0

        for i, (vendor_info, profile) in enumerate(zip(VENDORS, VENDOR_PROFILES)):
            name, contact_name, contact_email = vendor_info

            # Check if vendor already exists
            existing = db.query(Vendor).filter(Vendor.name == name).first()
            if existing:
                print(f"  Skipping {name} — already exists")
                continue

            # Create vendor
            vendor = Vendor(
                name=name,
                primary_contact_name=contact_name,
                primary_contact_email=contact_email,
                notes=f"Demo vendor — {profile['quality']} security posture",
                status=VENDOR_STATUS_ACTIVE if i < 9 else VENDOR_STATUS_ARCHIVED,
                created_at=datetime.utcnow() - timedelta(days=random.randint(30, 365)),
            )
            db.add(vendor)
            db.flush()
            created_vendors += 1

            # Pick random subset of categories and questions
            q_count = random.randint(*profile["q_range"])
            selected_cats = random.sample(cat_names, min(random.randint(3, 8), len(cat_names)))
            selected_items = []
            for cat in selected_cats:
                cat_items = categories[cat]
                take = min(random.randint(2, len(cat_items)), len(cat_items))
                selected_items.extend(random.sample(cat_items, take))
            random.shuffle(selected_items)
            selected_items = selected_items[:q_count]

            # Create assessment
            token = generate_unique_token(db)
            days_ago = random.randint(5, 180)
            assessment = Assessment(
                company_name=name,
                title=TITLES[i],
                token=token,
                vendor_id=vendor.id,
                status=ASSESSMENT_STATUS_REVIEWED,
                created_at=datetime.utcnow() - timedelta(days=days_ago),
                submitted_at=datetime.utcnow() - timedelta(days=days_ago - 3),
                reviewed_at=datetime.utcnow() - timedelta(days=max(1, days_ago - 10)),
            )
            db.add(assessment)
            db.flush()

            # Create questions
            questions = []
            for order, item in enumerate(selected_items):
                weight = random.choice(WEIGHT_DIST)
                expected = random.choice(["yes", "yes", "yes", "partial"])
                expected_list = ["yes"] if expected == "yes" else ["yes", "partial"]
                q = Question(
                    assessment_id=assessment.id,
                    question_text=item.text,
                    order=order,
                    weight=weight,
                    expected_operator="EQUALS",
                    expected_value=expected_list[0],
                    expected_values=json.dumps(expected_list),
                    expected_value_type="CHOICE",
                    answer_mode="SINGLE",
                    category=item.category,
                    question_bank_item_id=item.id,
                    answer_options=item.answer_options,
                )
                db.add(q)
                questions.append(q)
            db.flush()

            # Create response with answers
            response = Response(
                assessment_id=assessment.id,
                vendor_name=name,
                vendor_email=contact_email,
                status=RESPONSE_STATUS_SUBMITTED,
                submitted_at=assessment.submitted_at,
            )
            db.add(response)
            db.flush()

            for q in questions:
                answer_choice = pick_answer(profile["bias"])
                answer = Answer(
                    response_id=response.id,
                    question_id=q.id,
                    answer_choice=answer_choice,
                )
                db.add(answer)
            db.flush()

            # Compute scores to drive the decision
            scores = compute_assessment_scores(questions, response)
            overall_score = scores["overall_score"]
            risk_level = scores["suggested_risk_level"] if overall_score is not None else RISK_LEVEL_MODERATE
            outcome = risk_to_outcome(risk_level)

            # Create finalized assessment decision
            review_offset = random.randint(90, 365)
            quality = profile["quality"]
            decision = AssessmentDecision(
                vendor_id=vendor.id,
                assessment_id=assessment.id,
                status=DECISION_STATUS_FINAL,
                data_sensitivity=random.choice(SENSITIVITY_OPTIONS),
                business_criticality=random.choice(CRITICALITY_OPTIONS),
                impact_rating=random.choice([RISK_LEVEL_LOW, RISK_LEVEL_MODERATE, RISK_LEVEL_HIGH, RISK_LEVEL_VERY_HIGH]),
                likelihood_rating=random.choice([RISK_LEVEL_LOW, RISK_LEVEL_MODERATE, RISK_LEVEL_HIGH]),
                overall_risk_rating=risk_level,
                decision_outcome=outcome,
                rationale=random.choice(RATIONALE_TEMPLATES[quality]),
                key_findings=FINDINGS_TEMPLATES[quality],
                remediation_required=REMEDIATION_TEMPLATES[quality],
                next_review_date=datetime.utcnow() + timedelta(days=review_offset) if i < 7 else datetime.utcnow() - timedelta(days=random.randint(5, 60)),
                created_at=assessment.reviewed_at,
                finalized_at=assessment.reviewed_at,
            )
            db.add(decision)
            created_assessments += 1

            print(f"  {name}: {len(questions)} questions, score={overall_score}, risk={risk_level}, outcome={outcome}")

        # Also create a couple of in-progress/draft assessments (no decision) for pipeline variety
        extra_statuses = [
            (ASSESSMENT_STATUS_DRAFT, "Draft Security Review"),
            (ASSESSMENT_STATUS_SENT, "Pending Vendor Response"),
            (ASSESSMENT_STATUS_IN_PROGRESS, "In-Progress Assessment"),
            (ASSESSMENT_STATUS_SUBMITTED, "Awaiting Internal Review"),
        ]
        # Attach these to random existing vendors
        all_vendors = db.query(Vendor).all()
        for status, title in extra_statuses:
            v = random.choice(all_vendors)
            token = generate_unique_token(db)
            extra = Assessment(
                company_name=v.name,
                title=title,
                token=token,
                vendor_id=v.id,
                status=status,
                created_at=datetime.utcnow() - timedelta(days=random.randint(1, 30)),
            )
            db.add(extra)
            created_assessments += 1

        db.commit()
        print(f"\nDone! Created {created_vendors} vendors and {created_assessments} assessments.")

    finally:
        db.close()


if __name__ == "__main__":
    main()
