"""Seed comprehensive test data for the GRC platform."""
import json
import random
from datetime import datetime, timedelta

from models import (
    SessionLocal, Vendor, VendorContact, Assessment, Question, QuestionBankItem,
    Response, Answer, ReminderLog,
    VENDOR_STATUS_ACTIVE,
    REMINDER_TYPE_REMINDER, REMINDER_TYPE_ESCALATION,
    ensure_reminder_config,
)
from app.services.token import generate_unique_token

random.seed(42)
db = SessionLocal()
now = datetime.utcnow()

# ============================================================
# NEW VENDORS
# ============================================================
new_vendors = [
    {"name": "Palantir Data Systems", "industry": "Technology", "website": "https://palantirdata.example.com", "headquarters": "Denver, CO", "service_type": "SaaS", "data_classification": "Restricted", "business_criticality": "Critical", "access_level": "Full System Access", "tier_override": "Tier 1"},
    {"name": "Meridian HR Solutions", "industry": "Consulting", "website": "https://meridianhr.example.com", "headquarters": "Atlanta, GA", "service_type": "BPO", "data_classification": "Confidential", "business_criticality": "High", "access_level": "Employee Data", "tier_override": "Tier 1"},
    {"name": "Vaultline Backup Co", "industry": "Technology", "website": "https://vaultline.example.com", "headquarters": "Austin, TX", "service_type": "Infrastructure", "data_classification": "Confidential", "business_criticality": "High", "access_level": "Backup Systems"},
    {"name": "Clearpath Compliance", "industry": "Consulting", "website": "https://clearpathcompliance.example.com", "headquarters": "Washington, DC", "service_type": "Consulting", "data_classification": "Internal", "business_criticality": "Medium", "access_level": "Policy Documents", "tier_override": "Tier 2"},
    {"name": "Nimbus Cloud Hosting", "industry": "Technology", "website": "https://nimbuscloud.example.com", "headquarters": "San Jose, CA", "service_type": "Infrastructure", "data_classification": "Restricted", "business_criticality": "Critical", "access_level": "Full System Access", "tier_override": "Tier 1"},
    {"name": "SignalWave Analytics", "industry": "Technology", "website": "https://signalwave.example.com", "headquarters": "Boston, MA", "service_type": "SaaS", "data_classification": "Confidential", "business_criticality": "Medium", "access_level": "Analytics Data", "tier_override": "Tier 2"},
    {"name": "TerraFirm Legal Tech", "industry": "Legal", "website": "https://terrafirm.example.com", "headquarters": "Chicago, IL", "service_type": "SaaS", "data_classification": "Restricted", "business_criticality": "High", "access_level": "Legal Records", "tier_override": "Tier 1"},
    {"name": "Brightfield Payroll", "industry": "Finance", "website": "https://brightfield.example.com", "headquarters": "Charlotte, NC", "service_type": "BPO", "data_classification": "Restricted", "business_criticality": "Critical", "access_level": "Financial Data", "tier_override": "Tier 1"},
    {"name": "Canopy IT Services", "industry": "Technology", "website": "https://canopyit.example.com", "headquarters": "Portland, OR", "service_type": "Consulting", "data_classification": "Internal", "business_criticality": "Low", "access_level": "IT Support", "tier_override": "Tier 3"},
    {"name": "Prism Security Group", "industry": "Technology", "website": "https://prismsec.example.com", "headquarters": "Seattle, WA", "service_type": "SaaS", "data_classification": "Confidential", "business_criticality": "High", "access_level": "Security Monitoring", "tier_override": "Tier 2"},
    {"name": "NovaEdge Software", "industry": "Technology", "website": "https://novaedge.example.com", "headquarters": "San Francisco, CA", "service_type": "SaaS", "data_classification": "Internal", "business_criticality": "Medium", "access_level": "Project Data"},
    {"name": "Redline Logistics", "industry": "Manufacturing", "website": "https://redlinelogistics.example.com", "headquarters": "Dallas, TX", "service_type": "BPO", "data_classification": "Internal", "business_criticality": "Low", "access_level": "Shipping Info", "tier_override": "Tier 3"},
    {"name": "BlueHarbor Finance", "industry": "Finance", "website": "https://blueharbor.example.com", "headquarters": "New York, NY", "service_type": "SaaS", "data_classification": "Restricted", "business_criticality": "Critical", "access_level": "Financial Data", "tier_override": "Tier 1"},
    {"name": "Keystroke Digital", "industry": "Technology", "website": "https://keystrokedigital.example.com", "headquarters": "Nashville, TN", "service_type": "SaaS", "data_classification": "Public", "business_criticality": "Low", "access_level": "Marketing Data", "tier_override": "Tier 3"},
    {"name": "Atlas Managed Services", "industry": "Technology", "website": "https://atlasms.example.com", "headquarters": "Phoenix, AZ", "service_type": "Infrastructure", "data_classification": "Confidential", "business_criticality": "High", "access_level": "Server Infrastructure", "tier_override": "Tier 2"},
    {"name": "Cordoba Health Systems", "industry": "Healthcare", "website": "https://cordobahealth.example.com", "headquarters": "Miami, FL", "service_type": "SaaS", "data_classification": "Restricted", "business_criticality": "Critical", "access_level": "PHI Data", "tier_override": "Tier 1"},
    {"name": "Evergreen Document Mgmt", "industry": "Technology", "website": "https://evergreendm.example.com", "headquarters": "Minneapolis, MN", "service_type": "SaaS", "data_classification": "Confidential", "business_criticality": "Medium", "access_level": "Document Storage"},
    {"name": "Zenith Telecom", "industry": "Telecommunications", "website": "https://zenithtelecom.example.com", "headquarters": "Raleigh, NC", "service_type": "Infrastructure", "data_classification": "Internal", "business_criticality": "Medium", "access_level": "Voice/Data Networks", "tier_override": "Tier 2"},
]

for v_data in new_vendors:
    existing = db.query(Vendor).filter(Vendor.name == v_data["name"]).first()
    if existing:
        continue
    v = Vendor(status=VENDOR_STATUS_ACTIVE, **v_data)
    db.add(v)

db.flush()

# ============================================================
# CONTACTS for all vendors
# ============================================================
first_names = ["Sarah", "James", "Maria", "David", "Emily", "Michael", "Ana", "Robert",
               "Lisa", "John", "Jennifer", "Chris", "Amanda", "Daniel", "Rachel", "Kevin",
               "Nicole", "Brian", "Laura", "Mark", "Stephanie", "Andrew", "Jessica", "Thomas",
               "Michelle", "Ryan", "Megan", "Patrick", "Ashley", "Alex"]
last_names = ["Chen", "Williams", "Garcia", "Thompson", "Lee", "Martinez", "Johnson", "Robinson",
              "Clark", "Lewis", "Walker", "Hall", "Allen", "Young", "King", "Wright",
              "Adams", "Nelson", "Hill", "Scott", "Moore", "Taylor", "White", "Harris",
              "Martin", "Jackson", "Thomas", "Wilson", "Anderson", "Brown"]
contact_roles = ["Primary", "Security", "Technical"]

all_vendors = db.query(Vendor).filter(Vendor.status == VENDOR_STATUS_ACTIVE).all()
for i, vendor in enumerate(all_vendors):
    existing_contacts = db.query(VendorContact).filter(VendorContact.vendor_id == vendor.id).count()
    if existing_contacts > 0:
        continue
    domain = vendor.name.lower().replace(" ", "").replace(".", "")[:15] + ".com"
    for j, role in enumerate(contact_roles):
        fn = first_names[(i * 3 + j) % len(first_names)]
        ln = last_names[(i * 3 + j) % len(last_names)]
        contact = VendorContact(
            vendor_id=vendor.id,
            name=f"{fn} {ln}",
            email=f"{fn.lower()}.{ln.lower()}@{domain}",
            role=role,
            phone=f"+1-555-{random.randint(100,999)}-{random.randint(1000,9999)}",
        )
        db.add(contact)

db.flush()

# ============================================================
# ASSESSMENTS at various statuses
# ============================================================
bank_items = db.query(QuestionBankItem).filter(QuestionBankItem.is_active == True).limit(8).all()

scenarios = [
    # (vendor_name, title, status, days_created, days_sent, email, paused)
    # DRAFT
    ("Palantir Data Systems", "Initial Security Assessment", "DRAFT", 5, None, None, False),
    ("Canopy IT Services", "Annual IT Support Review", "DRAFT", 2, None, None, False),
    ("Keystroke Digital", "Marketing Platform Assessment", "DRAFT", 1, None, None, False),
    # SENT - various wait times
    ("Meridian HR Solutions", "HR Data Protection Assessment", "SENT", 18, 16, "sarah.chen@meridianhr.com", False),
    ("Nimbus Cloud Hosting", "Cloud Infrastructure Review", "SENT", 12, 10, "tech@nimbuscloud.com", False),
    ("TerraFirm Legal Tech", "Legal Data Security Review", "SENT", 8, 7, "james.williams@terrafirm.com", False),
    ("Brightfield Payroll", "Payroll System Security Audit", "SENT", 25, 22, "admin@brightfield.com", False),
    ("BlueHarbor Finance", "Financial Systems Assessment", "SENT", 15, 14, "security@blueharbor.com", False),
    ("Cordoba Health Systems", "HIPAA Compliance Assessment", "SENT", 6, 4, "maria.garcia@cordobahealth.com", False),
    ("Atlas Managed Services", "Infrastructure Security Review", "SENT", 10, 8, "david.thompson@atlasms.com", True),
    ("Evergreen Document Mgmt", "Document Security Assessment", "SENT", 3, 2, "emily.lee@evergreendm.com", False),
    # IN_PROGRESS
    ("SignalWave Analytics", "Analytics Platform Assessment", "IN_PROGRESS", 14, 12, "michael.martinez@signalwave.com", False),
    ("Prism Security Group", "Security Tools Assessment", "IN_PROGRESS", 9, 7, "ana.johnson@prismsec.com", False),
    ("Vaultline Backup Co", "Backup Systems Review", "IN_PROGRESS", 20, 18, "robert.robinson@vaultline.com", False),
    # SUBMITTED
    ("Clearpath Compliance", "Compliance Framework Review", "SUBMITTED", 30, 28, "lisa.clark@clearpath.com", False),
    ("NovaEdge Software", "Software Security Assessment", "SUBMITTED", 22, 20, "john.lewis@novaedge.com", False),
    ("Redline Logistics", "Logistics Platform Review", "SUBMITTED", 15, 13, "jennifer.walker@redline.com", False),
    ("Zenith Telecom", "Telecom Infrastructure Assessment", "SUBMITTED", 20, 18, "chris.hall@zenithtelecom.com", False),
]

for vendor_name, title, status, days_created, days_sent, email, paused in scenarios:
    vendor = db.query(Vendor).filter(Vendor.name == vendor_name).first()
    if not vendor:
        continue
    existing = db.query(Assessment).filter(
        Assessment.vendor_id == vendor.id, Assessment.title == title
    ).first()
    if existing:
        continue

    token = generate_unique_token(db)
    a = Assessment(
        company_name=vendor.name,
        title=title,
        token=token,
        vendor_id=vendor.id,
        status=status,
        created_at=now - timedelta(days=days_created),
        sent_at=(now - timedelta(days=days_sent)) if days_sent else None,
        sent_to_email=email,
        expires_at=(now - timedelta(days=days_sent) + timedelta(days=30)) if days_sent else None,
        reminders_paused=paused,
        submitted_at=(now - timedelta(days=days_created - 2)) if status == "SUBMITTED" else None,
    )
    db.add(a)
    db.flush()

    # Add questions from bank
    for idx, bi in enumerate(bank_items[:5]):
        q = Question(
            assessment_id=a.id,
            question_text=bi.text,
            order=idx,
            weight="MEDIUM" if idx < 3 else "HIGH",
            expected_operator="EQUALS",
            expected_value="yes",
            expected_value_type="CHOICE",
            answer_mode="SINGLE",
            category=bi.category,
            question_bank_item_id=bi.id,
            answer_options=bi.answer_options,
        )
        db.add(q)

    # For SUBMITTED, create response + answers
    if status == "SUBMITTED":
        db.flush()
        resp = Response(
            assessment_id=a.id,
            vendor_name=f"{vendor.name} Security Team",
            vendor_email=email or f"security@example.com",
            status="SUBMITTED",
            submitted_at=a.submitted_at,
        )
        db.add(resp)
        db.flush()

        questions = db.query(Question).filter(Question.assessment_id == a.id).all()
        answer_vals = ["yes", "yes", "partial", "yes", "no"]
        for idx, q in enumerate(questions):
            ans = Answer(
                response_id=resp.id,
                question_id=q.id,
                answer_choice=answer_vals[idx % len(answer_vals)],
            )
            db.add(ans)

db.flush()

# ============================================================
# REMINDER LOGS
# ============================================================
reminder_scenarios = [
    ("Meridian HR Solutions", "HR Data Protection Assessment", [
        (REMINDER_TYPE_REMINDER, 1, 13),
        (REMINDER_TYPE_REMINDER, 2, 6),
        (REMINDER_TYPE_ESCALATION, 2, 5),
    ]),
    ("Brightfield Payroll", "Payroll System Security Audit", [
        (REMINDER_TYPE_REMINDER, 1, 19),
        (REMINDER_TYPE_REMINDER, 2, 12),
        (REMINDER_TYPE_REMINDER, 3, 5),
        (REMINDER_TYPE_ESCALATION, 3, 4),
    ]),
    ("BlueHarbor Finance", "Financial Systems Assessment", [
        (REMINDER_TYPE_REMINDER, 1, 11),
        (REMINDER_TYPE_REMINDER, 2, 4),
    ]),
    ("Nimbus Cloud Hosting", "Cloud Infrastructure Review", [
        (REMINDER_TYPE_REMINDER, 1, 7),
    ]),
    ("TerraFirm Legal Tech", "Legal Data Security Review", [
        (REMINDER_TYPE_REMINDER, 1, 4),
    ]),
    ("SignalWave Analytics", "Analytics Platform Assessment", [
        (REMINDER_TYPE_REMINDER, 1, 9),
        (REMINDER_TYPE_REMINDER, 2, 2),
    ]),
    ("Vaultline Backup Co", "Backup Systems Review", [
        (REMINDER_TYPE_REMINDER, 1, 15),
        (REMINDER_TYPE_REMINDER, 2, 8),
        (REMINDER_TYPE_REMINDER, 3, 1),
        (REMINDER_TYPE_ESCALATION, 3, 1),
    ]),
    ("Prism Security Group", "Security Tools Assessment", [
        (REMINDER_TYPE_REMINDER, 1, 4),
    ]),
]

for vendor_name, title, entries in reminder_scenarios:
    vendor = db.query(Vendor).filter(Vendor.name == vendor_name).first()
    if not vendor:
        continue
    assessment = db.query(Assessment).filter(
        Assessment.vendor_id == vendor.id, Assessment.title == title
    ).first()
    if not assessment:
        continue
    for rtype, rnum, days_ago in entries:
        existing = db.query(ReminderLog).filter(
            ReminderLog.assessment_id == assessment.id,
            ReminderLog.reminder_type == rtype,
            ReminderLog.reminder_number == rnum,
        ).first()
        if existing:
            continue
        log = ReminderLog(
            assessment_id=assessment.id,
            to_email=assessment.sent_to_email or f"contact@example.com",
            reminder_number=rnum,
            reminder_type=rtype,
            sent_at=now - timedelta(days=days_ago),
        )
        db.add(log)

db.commit()

# ============================================================
# SUMMARY
# ============================================================
print()
print("=== SEED COMPLETE ===")
print(f"Active vendors:  {db.query(Vendor).filter(Vendor.status == VENDOR_STATUS_ACTIVE).count()}")
print(f"Total contacts:  {db.query(VendorContact).count()}")
print(f"Total assessments: {db.query(Assessment).count()}")
print(f"  DRAFT:       {db.query(Assessment).filter(Assessment.status == 'DRAFT').count()}")
print(f"  SENT:        {db.query(Assessment).filter(Assessment.status == 'SENT').count()}")
print(f"  IN_PROGRESS: {db.query(Assessment).filter(Assessment.status == 'IN_PROGRESS').count()}")
print(f"  SUBMITTED:   {db.query(Assessment).filter(Assessment.status == 'SUBMITTED').count()}")
print(f"  REVIEWED:    {db.query(Assessment).filter(Assessment.status == 'REVIEWED').count()}")
print(f"Reminder logs: {db.query(ReminderLog).count()}")
db.close()
