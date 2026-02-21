from sqlalchemy import create_engine, Column, Integer, String, Text, ForeignKey, DateTime, Boolean, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime

DATABASE_URL = "sqlite:///./questionnaires.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False)
    display_name = Column(String(255), nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False, default="analyst")  # admin, analyst, viewer
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login_at = Column(DateTime, nullable=True)
    onboarding_dismissed = Column(Boolean, default=False)


VALID_ROLES = ["admin", "analyst", "viewer"]


class QuestionBankItem(Base):
    __tablename__ = "question_bank_items"

    id = Column(Integer, primary_key=True, index=True)
    category = Column(String(100), nullable=False, index=True)
    text = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True)
    answer_options = Column(Text, nullable=True)
    framework_ref = Column(Text, nullable=True)  # comma-separated framework keys
    created_at = Column(DateTime, default=datetime.utcnow)


# Industry-standard frameworks for question mapping
AVAILABLE_FRAMEWORKS = [
    ("NIST_CSF_2", "NIST CSF 2.0"),
    ("ISO_27001", "ISO 27001:2022"),
    ("SOC_2", "SOC 2"),
    ("NIST_800_53", "NIST SP 800-53 Rev 5"),
    ("CIS_V8", "CIS Controls v8"),
    ("SIG", "SIG / SIG Lite"),
    ("PCI_DSS_4", "PCI DSS v4.0"),
    ("HIPAA", "HIPAA"),
    ("GDPR", "GDPR"),
    ("CSA_CCM_4", "CSA CCM v4"),
    ("COBIT_2019", "COBIT 2019"),
    ("CMMC_2", "CMMC 2.0"),
]

# Lookup dict for display names
FRAMEWORK_DISPLAY = {key: label for key, label in AVAILABLE_FRAMEWORKS}


VENDOR_STATUS_ACTIVE = "ACTIVE"
VENDOR_STATUS_ARCHIVED = "ARCHIVED"
# VALID_VENDOR_STATUSES defined below after VENDOR_STATUS_OFFBOARDING

VALID_INDUSTRIES = ["Technology", "Healthcare", "Finance", "Manufacturing", "Retail", "Energy", "Telecommunications", "Government", "Education", "Legal", "Consulting", "Other"]
VALID_SERVICE_TYPES = ["SaaS", "Infrastructure", "BPO", "Consulting", "Hardware", "Other"]
VALID_DATA_CLASSIFICATIONS = ["Public", "Internal", "Confidential", "Restricted"]
VALID_BUSINESS_CRITICALITIES = ["Low", "Medium", "High", "Critical"]
VALID_ACCESS_LEVELS = ["None", "Limited", "Moderate", "Extensive"]
VALID_INHERENT_RISK_TIERS = ["Tier 1", "Tier 2", "Tier 3"]
VALID_CONTACT_ROLES = ["Primary", "Security", "Legal", "Executive", "Technical", "Other"]
VALID_DOCUMENT_TYPES = ["SOC2_REPORT", "ISO_CERT", "INSURANCE", "CONTRACT", "NDA", "POLICY", "PENTEST_REPORT", "OTHER"]
DOCUMENT_TYPE_LABELS = {
    "SOC2_REPORT": "SOC 2 Report",
    "ISO_CERT": "ISO Certification",
    "INSURANCE": "Insurance Certificate",
    "CONTRACT": "Contract",
    "NDA": "NDA",
    "POLICY": "Policy Document",
    "PENTEST_REPORT": "Pentest Report",
    "OTHER": "Other",
}


class Vendor(Base):
    __tablename__ = "vendors"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    primary_contact_name = Column(String(255), nullable=True)
    primary_contact_email = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)
    status = Column(String(20), default=VENDOR_STATUS_ACTIVE, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Enrichment fields
    industry = Column(String(100), nullable=True)
    website = Column(String(500), nullable=True)
    headquarters = Column(String(255), nullable=True)
    service_type = Column(String(50), nullable=True)

    # Risk classification
    data_classification = Column(String(50), nullable=True)
    business_criticality = Column(String(20), nullable=True)
    access_level = Column(String(50), nullable=True)

    # Inherent risk tiering
    inherent_risk_tier = Column(String(20), nullable=True)
    tier_override = Column(String(20), nullable=True)
    tier_notes = Column(Text, nullable=True)

    # Contract information
    contract_start_date = Column(DateTime, nullable=True)
    contract_end_date = Column(DateTime, nullable=True)
    contract_value = Column(String(100), nullable=True)
    auto_renewal = Column(Boolean, default=False)

    # Analyst assignment
    assigned_analyst_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    assigned_analyst = relationship("User", foreign_keys=[assigned_analyst_id])

    # Offboarding
    offboarding_checklist = Column(Text, nullable=True)  # JSON checklist

    assessments = relationship("Assessment", back_populates="vendor")
    contacts = relationship("VendorContact", back_populates="vendor", cascade="all, delete-orphan")
    documents = relationship("VendorDocument", back_populates="vendor", cascade="all, delete-orphan")


class VendorContact(Base):
    __tablename__ = "vendor_contacts"

    id = Column(Integer, primary_key=True, index=True)
    vendor_id = Column(Integer, ForeignKey("vendors.id"), nullable=False)
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=True)
    role = Column(String(50), nullable=True)
    phone = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    vendor = relationship("Vendor", back_populates="contacts")


class VendorDocument(Base):
    __tablename__ = "vendor_documents"

    id = Column(Integer, primary_key=True, index=True)
    vendor_id = Column(Integer, ForeignKey("vendors.id"), nullable=False)
    document_type = Column(String(50), nullable=False)
    title = Column(String(255), nullable=False)
    original_filename = Column(String(255), nullable=False)
    stored_filename = Column(String(255), nullable=False)
    stored_path = Column(String(512), nullable=False)
    content_type = Column(String(100), nullable=True)
    size_bytes = Column(Integer, nullable=True)
    expiry_date = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)
    uploaded_at = Column(DateTime, default=datetime.utcnow)

    vendor = relationship("Vendor", back_populates="documents")


# ==================== ASSESSMENT TEMPLATE ====================

class AssessmentTemplate(Base):
    __tablename__ = "assessment_templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    source_title = Column(String(255), nullable=True)
    source_company = Column(String(255), nullable=True)
    token = Column(String(64), unique=True, nullable=False, index=True)
    suggested_tier = Column(String(20), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    template_questions = relationship("TemplateQuestion", back_populates="template", cascade="all, delete-orphan")
    template_rules = relationship("TemplateConditionalRule", back_populates="template", cascade="all, delete-orphan")


class TemplateQuestion(Base):
    __tablename__ = "template_questions"

    id = Column(Integer, primary_key=True, index=True)
    template_id = Column(Integer, ForeignKey("assessment_templates.id"), nullable=False)
    question_text = Column(Text, nullable=False)
    order = Column(Integer, default=0)
    weight = Column(String(20), default="MEDIUM", nullable=False)
    expected_operator = Column(String(20), default="EQUALS", nullable=False)
    expected_value = Column(String(50), nullable=True)
    expected_values = Column(Text, nullable=True)
    expected_value_type = Column(String(20), default="CHOICE", nullable=False)
    answer_mode = Column(String(20), default="SINGLE", nullable=False)
    category = Column(String(100), nullable=True, index=True)
    answer_options = Column(Text, nullable=True)

    template = relationship("AssessmentTemplate", back_populates="template_questions")


class TemplateConditionalRule(Base):
    __tablename__ = "template_conditional_rules"

    id = Column(Integer, primary_key=True, index=True)
    template_id = Column(Integer, ForeignKey("assessment_templates.id"), nullable=False)
    trigger_question_id = Column(Integer, ForeignKey("template_questions.id"), nullable=False)
    operator = Column(String(20), default="IN", nullable=False)
    trigger_values = Column(Text, nullable=False)
    target_question_id = Column(Integer, ForeignKey("template_questions.id"), nullable=False)
    make_required = Column(Boolean, default=False, nullable=False)

    template = relationship("AssessmentTemplate", back_populates="template_rules")
    trigger_question = relationship("TemplateQuestion", foreign_keys=[trigger_question_id])
    target_question = relationship("TemplateQuestion", foreign_keys=[target_question_id])


# ==================== ASSESSMENT (LIVE INSTANCE) ====================

ASSESSMENT_STATUS_DRAFT = "DRAFT"
ASSESSMENT_STATUS_SENT = "SENT"
ASSESSMENT_STATUS_IN_PROGRESS = "IN_PROGRESS"
ASSESSMENT_STATUS_SUBMITTED = "SUBMITTED"
ASSESSMENT_STATUS_REVIEWED = "REVIEWED"
VALID_ASSESSMENT_STATUSES = [
    ASSESSMENT_STATUS_DRAFT,
    ASSESSMENT_STATUS_SENT,
    ASSESSMENT_STATUS_IN_PROGRESS,
    ASSESSMENT_STATUS_SUBMITTED,
    ASSESSMENT_STATUS_REVIEWED
]


class Assessment(Base):
    __tablename__ = "assessments"

    id = Column(Integer, primary_key=True, index=True)
    company_name = Column(String(255), nullable=False)
    title = Column(String(255), nullable=False)
    token = Column(String(64), unique=True, nullable=False, index=True)
    vendor_id = Column(Integer, ForeignKey("vendors.id"), nullable=True)
    template_id = Column(Integer, ForeignKey("assessment_templates.id"), nullable=True)
    status = Column(String(20), default=ASSESSMENT_STATUS_DRAFT, nullable=False)
    sent_at = Column(DateTime, nullable=True)
    sent_to_email = Column(String(255), nullable=True)
    expires_at = Column(DateTime, nullable=True)
    reminders_paused = Column(Boolean, default=False)
    first_reminder_days = Column(Integer, nullable=True)
    reminder_frequency_days = Column(Integer, nullable=True)
    max_reminders = Column(Integer, nullable=True)
    submitted_at = Column(DateTime, nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    previous_assessment_id = Column(Integer, ForeignKey("assessments.id"), nullable=True)
    assigned_analyst_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    vendor = relationship("Vendor", back_populates="assessments")
    template = relationship("AssessmentTemplate")
    questions = relationship("Question", back_populates="assessment", cascade="all, delete-orphan")
    responses = relationship("Response", back_populates="assessment", cascade="all, delete-orphan")
    conditional_rules = relationship("ConditionalRule", back_populates="assessment", cascade="all, delete-orphan")
    previous_assessment = relationship("Assessment", remote_side="Assessment.id", uselist=False)
    assigned_analyst = relationship("User", foreign_keys=[assigned_analyst_id])


WEIGHT_LOW = "LOW"
WEIGHT_MEDIUM = "MEDIUM"
WEIGHT_HIGH = "HIGH"
WEIGHT_CRITICAL = "CRITICAL"
VALID_WEIGHTS = [WEIGHT_LOW, WEIGHT_MEDIUM, WEIGHT_HIGH, WEIGHT_CRITICAL]

OPERATOR_EQUALS = "EQUALS"
VALID_OPERATORS = [OPERATOR_EQUALS]

VALUE_TYPE_CHOICE = "CHOICE"
VALUE_TYPE_NUMBER = "NUMBER"
VALUE_TYPE_TEXT = "TEXT"
VALID_VALUE_TYPES = [VALUE_TYPE_CHOICE, VALUE_TYPE_NUMBER, VALUE_TYPE_TEXT]

ANSWER_MODE_SINGLE = "SINGLE"
ANSWER_MODE_MULTI = "MULTI"
VALID_ANSWER_MODES = [ANSWER_MODE_SINGLE, ANSWER_MODE_MULTI]


class Question(Base):
    __tablename__ = "questions"

    id = Column(Integer, primary_key=True, index=True)
    assessment_id = Column(Integer, ForeignKey("assessments.id"), nullable=False)
    question_text = Column(Text, nullable=False)
    order = Column(Integer, default=0)
    weight = Column(String(20), default=WEIGHT_MEDIUM, nullable=False)
    expected_operator = Column(String(20), default=OPERATOR_EQUALS, nullable=False)
    expected_value = Column(String(50), nullable=True)
    expected_values = Column(Text, nullable=True)
    expected_value_type = Column(String(20), default=VALUE_TYPE_CHOICE, nullable=False)
    answer_mode = Column(String(20), default=ANSWER_MODE_SINGLE, nullable=False)
    category = Column(String(100), nullable=True, index=True)
    question_bank_item_id = Column(Integer, ForeignKey("question_bank_items.id"), nullable=True)
    answer_options = Column(Text, nullable=True)

    assessment = relationship("Assessment", back_populates="questions")
    question_bank_item = relationship("QuestionBankItem")


RESPONSE_STATUS_DRAFT = "DRAFT"
RESPONSE_STATUS_SUBMITTED = "SUBMITTED"
RESPONSE_STATUS_NEEDS_INFO = "NEEDS_INFO"


class Response(Base):
    __tablename__ = "responses"

    id = Column(Integer, primary_key=True, index=True)
    assessment_id = Column(Integer, ForeignKey("assessments.id"), nullable=False)
    vendor_name = Column(String(255), nullable=False)
    vendor_email = Column(String(255), nullable=False)
    status = Column(String(20), default=RESPONSE_STATUS_DRAFT, nullable=False)
    submitted_at = Column(DateTime, default=datetime.utcnow)
    last_saved_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    assessment = relationship("Assessment", back_populates="responses")
    answers = relationship("Answer", back_populates="response", cascade="all, delete-orphan")
    evidence_files = relationship("EvidenceFile", back_populates="response", cascade="all, delete-orphan")
    follow_ups = relationship("FollowUp", back_populates="response", cascade="all, delete-orphan")


class Answer(Base):
    __tablename__ = "answers"

    id = Column(Integer, primary_key=True, index=True)
    response_id = Column(Integer, ForeignKey("responses.id"), nullable=False)
    question_id = Column(Integer, ForeignKey("questions.id"), nullable=False)
    answer_choice = Column(String(255), nullable=True)
    answer_text = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)

    response = relationship("Response", back_populates="answers")
    question = relationship("Question")


class EvidenceFile(Base):
    __tablename__ = "evidence_files"

    id = Column(Integer, primary_key=True, index=True)
    assessment_id = Column(Integer, ForeignKey("assessments.id"), nullable=False)
    response_id = Column(Integer, ForeignKey("responses.id"), nullable=False)
    original_filename = Column(String(255), nullable=False)
    stored_filename = Column(String(255), nullable=False)
    stored_path = Column(String(512), nullable=False)
    content_type = Column(String(100), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    module = Column(String(50), default="vendor_risk", nullable=False, index=True)

    assessment = relationship("Assessment")
    response = relationship("Response", back_populates="evidence_files")


class FollowUp(Base):
    __tablename__ = "follow_ups"

    id = Column(Integer, primary_key=True, index=True)
    response_id = Column(Integer, ForeignKey("responses.id"), nullable=False)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    response_text = Column(Text, nullable=True)
    responded_at = Column(DateTime, nullable=True)
    module = Column(String(50), default="vendor_risk", nullable=False, index=True)

    response = relationship("Response", back_populates="follow_ups")


class ConditionalRule(Base):
    __tablename__ = "conditional_rules"

    id = Column(Integer, primary_key=True, index=True)
    assessment_id = Column(Integer, ForeignKey("assessments.id"), nullable=False)
    trigger_question_id = Column(Integer, ForeignKey("questions.id"), nullable=False)
    operator = Column(String(20), default="IN", nullable=False)
    trigger_values = Column(Text, nullable=False)
    target_question_id = Column(Integer, ForeignKey("questions.id"), nullable=False)
    make_required = Column(Boolean, default=False, nullable=False)

    assessment = relationship("Assessment", back_populates="conditional_rules")
    trigger_question = relationship("Question", foreign_keys=[trigger_question_id])
    target_question = relationship("Question", foreign_keys=[target_question_id])


DECISION_STATUS_DRAFT = "DRAFT"
DECISION_STATUS_PENDING_APPROVAL = "PENDING_APPROVAL"
DECISION_STATUS_FINAL = "FINAL"
VALID_DECISION_STATUSES = [DECISION_STATUS_DRAFT, DECISION_STATUS_PENDING_APPROVAL, DECISION_STATUS_FINAL]

RISK_LEVEL_VERY_LOW = "VERY_LOW"
RISK_LEVEL_LOW = "LOW"
RISK_LEVEL_MODERATE = "MODERATE"
RISK_LEVEL_HIGH = "HIGH"
RISK_LEVEL_VERY_HIGH = "VERY_HIGH"
VALID_RISK_LEVELS = [RISK_LEVEL_VERY_LOW, RISK_LEVEL_LOW, RISK_LEVEL_MODERATE, RISK_LEVEL_HIGH, RISK_LEVEL_VERY_HIGH]

DECISION_APPROVE = "APPROVE"
DECISION_APPROVE_WITH_CONDITIONS = "APPROVE_WITH_CONDITIONS"
DECISION_NEEDS_FOLLOW_UP = "NEEDS_FOLLOW_UP"
DECISION_REJECT = "REJECT"
VALID_DECISION_OUTCOMES = [DECISION_APPROVE, DECISION_APPROVE_WITH_CONDITIONS, DECISION_NEEDS_FOLLOW_UP, DECISION_REJECT]


class AssessmentDecision(Base):
    __tablename__ = "assessment_decisions"

    id = Column(Integer, primary_key=True, index=True)
    vendor_id = Column(Integer, ForeignKey("vendors.id"), nullable=False)
    assessment_id = Column(Integer, ForeignKey("assessments.id"), nullable=False)
    status = Column(String(20), default=DECISION_STATUS_DRAFT, nullable=False)
    data_sensitivity = Column(String(20), nullable=True)
    business_criticality = Column(String(20), nullable=True)
    impact_rating = Column(String(20), nullable=True)
    likelihood_rating = Column(String(20), nullable=True)
    overall_risk_rating = Column(String(20), nullable=True)
    decision_outcome = Column(String(30), nullable=True)
    rationale = Column(Text, nullable=True)
    key_findings = Column(Text, nullable=True)
    remediation_required = Column(Text, nullable=True)
    next_review_date = Column(DateTime, nullable=True)
    overall_score = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    finalized_at = Column(DateTime, nullable=True)
    decided_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Multi-approver (maker/checker) fields
    requires_approval = Column(Boolean, default=False)
    approval_status = Column(String(20), nullable=True)
    approved_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    approval_notes = Column(Text, nullable=True)
    approved_at = Column(DateTime, nullable=True)

    vendor = relationship("Vendor")
    assessment = relationship("Assessment")
    decided_by = relationship("User", foreign_keys=[decided_by_id])
    approved_by = relationship("User", foreign_keys=[approved_by_id])


# ==================== REMEDIATION ====================

REMEDIATION_SOURCE_AUTO = "AUTO"
REMEDIATION_SOURCE_MANUAL = "MANUAL"
VALID_REMEDIATION_SOURCES = [REMEDIATION_SOURCE_AUTO, REMEDIATION_SOURCE_MANUAL]

REMEDIATION_STATUS_OPEN = "OPEN"
REMEDIATION_STATUS_IN_PROGRESS = "IN_PROGRESS"
REMEDIATION_STATUS_EVIDENCE_SUBMITTED = "EVIDENCE_SUBMITTED"
REMEDIATION_STATUS_VERIFIED = "VERIFIED"
REMEDIATION_STATUS_CLOSED = "CLOSED"
VALID_REMEDIATION_STATUSES = [
    REMEDIATION_STATUS_OPEN, REMEDIATION_STATUS_IN_PROGRESS,
    REMEDIATION_STATUS_EVIDENCE_SUBMITTED, REMEDIATION_STATUS_VERIFIED,
    REMEDIATION_STATUS_CLOSED,
]

REMEDIATION_STATUS_LABELS = {
    REMEDIATION_STATUS_OPEN: "Open",
    REMEDIATION_STATUS_IN_PROGRESS: "In Progress",
    REMEDIATION_STATUS_EVIDENCE_SUBMITTED: "Evidence Submitted",
    REMEDIATION_STATUS_VERIFIED: "Verified",
    REMEDIATION_STATUS_CLOSED: "Closed",
}

REMEDIATION_STATUS_COLORS = {
    REMEDIATION_STATUS_OPEN: "#dc3545",
    REMEDIATION_STATUS_IN_PROGRESS: "#fd7e14",
    REMEDIATION_STATUS_EVIDENCE_SUBMITTED: "#0dcaf0",
    REMEDIATION_STATUS_VERIFIED: "#198754",
    REMEDIATION_STATUS_CLOSED: "#6c757d",
}


class RemediationItem(Base):
    __tablename__ = "remediation_items"

    id = Column(Integer, primary_key=True, index=True)
    vendor_id = Column(Integer, ForeignKey("vendors.id"), nullable=False)
    assessment_id = Column(Integer, ForeignKey("assessments.id"), nullable=True)
    decision_id = Column(Integer, ForeignKey("assessment_decisions.id"), nullable=True)
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    source = Column(String(20), default=REMEDIATION_SOURCE_MANUAL, nullable=False)
    risk_statement_id = Column(Integer, ForeignKey("risk_statements.id"), nullable=True)
    category = Column(String(100), nullable=True)
    severity = Column(String(20), default="MEDIUM", nullable=False)
    status = Column(String(30), default=REMEDIATION_STATUS_OPEN, nullable=False)
    assigned_to = Column(String(255), nullable=True)  # legacy free-text
    assigned_to_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    due_date = Column(DateTime, nullable=True)
    completed_date = Column(DateTime, nullable=True)
    evidence_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    vendor = relationship("Vendor")
    assessment = relationship("Assessment")
    decision = relationship("AssessmentDecision")
    risk_statement = relationship("RiskStatement")
    assigned_user = relationship("User", foreign_keys=[assigned_to_user_id])


# ==================== RISK STATEMENT LIBRARY ====================

TRIGGER_CATEGORY_HAS_DNM = "CATEGORY_HAS_DNM"
TRIGGER_PARTIAL_HIGH_CRITICAL = "PARTIAL_HIGH_CRITICAL"
TRIGGER_CATEGORY_SCORE_BELOW_50 = "CATEGORY_SCORE_BELOW_50"
TRIGGER_QUESTION_ANSWERED = "QUESTION_ANSWERED"
VALID_TRIGGER_CONDITIONS = [TRIGGER_CATEGORY_HAS_DNM, TRIGGER_PARTIAL_HIGH_CRITICAL, TRIGGER_CATEGORY_SCORE_BELOW_50, TRIGGER_QUESTION_ANSWERED]

SEVERITY_LOW = "LOW"
SEVERITY_MEDIUM = "MEDIUM"
SEVERITY_HIGH = "HIGH"
SEVERITY_CRITICAL = "CRITICAL"
VALID_SEVERITIES = [SEVERITY_LOW, SEVERITY_MEDIUM, SEVERITY_HIGH, SEVERITY_CRITICAL]

TRIGGER_LABELS = {
    TRIGGER_CATEGORY_HAS_DNM: "Any question does not meet expectation",
    TRIGGER_PARTIAL_HIGH_CRITICAL: "Partial answer on HIGH/CRITICAL weight question",
    TRIGGER_CATEGORY_SCORE_BELOW_50: "Category score below 50%",
    TRIGGER_QUESTION_ANSWERED: "Specific question answered",
}


class RiskStatement(Base):
    __tablename__ = "risk_statements"

    id = Column(Integer, primary_key=True, index=True)
    category = Column(String(100), nullable=False, index=True)
    trigger_condition = Column(String(50), nullable=False)
    severity = Column(String(20), default=SEVERITY_MEDIUM, nullable=False)
    finding_text = Column(Text, nullable=False)
    remediation_text = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    trigger_question_id = Column(Integer, ForeignKey("question_bank_items.id"), nullable=True)
    trigger_answer_value = Column(String(255), nullable=True)

    trigger_question = relationship("QuestionBankItem")


# ---------------------------------------------------------------------------
# Reminder system
# ---------------------------------------------------------------------------

REMINDER_TYPE_INITIAL = "INITIAL"
REMINDER_TYPE_REMINDER = "REMINDER"
REMINDER_TYPE_ESCALATION = "ESCALATION"
REMINDER_TYPE_FINAL = "FINAL_NOTICE"


class ReminderConfig(Base):
    """Global reminder settings — single row table."""
    __tablename__ = "reminder_config"

    id = Column(Integer, primary_key=True, index=True)
    enabled = Column(Boolean, default=True)
    first_reminder_days = Column(Integer, default=3)
    frequency_days = Column(Integer, default=7)
    max_reminders = Column(Integer, default=3)
    escalation_after = Column(Integer, default=2)
    escalation_email = Column(String(255), nullable=True)
    final_notice_days_before_expiry = Column(Integer, default=3)
    sla_enabled = Column(Boolean, default=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ReminderLog(Base):
    """Tracks every reminder sent."""
    __tablename__ = "reminder_logs"

    id = Column(Integer, primary_key=True, index=True)
    assessment_id = Column(Integer, ForeignKey("assessments.id"), nullable=False)
    to_email = Column(String(255), nullable=False)
    reminder_number = Column(Integer, default=1)
    reminder_type = Column(String(20), default=REMINDER_TYPE_REMINDER)
    sent_at = Column(DateTime, default=datetime.utcnow)

    assessment = relationship("Assessment")


def ensure_reminder_config(db_session):
    """Ensure a default ReminderConfig row exists."""
    config = db_session.query(ReminderConfig).first()
    if not config:
        config = ReminderConfig()
        db_session.add(config)
        db_session.commit()
    return config


VALID_CHOICES = ["yes", "no", "partial", "na"]

EVAL_MEETS = "MEETS_EXPECTATION"
EVAL_PARTIAL = "PARTIALLY_MEETS_EXPECTATION"
EVAL_DOES_NOT_MEET = "DOES_NOT_MEET_EXPECTATION"
EVAL_NO_EXPECTATION = "NO_EXPECTATION_DEFINED"


def get_answer_options(obj):
    """Parse answer_options JSON from a Question/TemplateQuestion/QuestionBankItem, or return VALID_CHOICES as default."""
    import json
    if obj and getattr(obj, 'answer_options', None):
        try:
            parsed = json.loads(obj.answer_options)
            if isinstance(parsed, list) and len(parsed) > 0:
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
    return list(VALID_CHOICES)


def has_custom_answer_options(obj):
    """True if obj uses non-default (custom) answer options."""
    import json
    if obj and getattr(obj, 'answer_options', None):
        try:
            parsed = json.loads(obj.answer_options)
            if isinstance(parsed, list) and len(parsed) > 0:
                return True
        except (json.JSONDecodeError, TypeError):
            pass
    return False


def compute_expectation_status(expected_value, answer_choice, expected_values=None, answer_mode="SINGLE", answer_options=None):
    """
    Compute evaluation status by comparing vendor answer to expected answer(s).
    Returns one of: EVAL_MEETS, EVAL_PARTIAL, EVAL_DOES_NOT_MEET, EVAL_NO_EXPECTATION

    If answer_options is set (custom answers), scoring is binary: MEETS or DOES_NOT_MEET only.
    """
    import json

    is_custom = False
    if answer_options:
        try:
            parsed = json.loads(answer_options) if isinstance(answer_options, str) else answer_options
            if isinstance(parsed, list) and len(parsed) > 0:
                is_custom = True
        except (json.JSONDecodeError, TypeError):
            pass

    expected_set = set()
    if expected_values:
        try:
            parsed = json.loads(expected_values)
            if isinstance(parsed, list):
                expected_set = set(v.lower() for v in parsed if v)
        except (json.JSONDecodeError, TypeError):
            pass

    if not expected_set and expected_value:
        expected_set = {expected_value.lower()}

    if not expected_set:
        return EVAL_NO_EXPECTATION

    if not answer_choice:
        return EVAL_DOES_NOT_MEET

    if answer_mode == "MULTI":
        answers = set(a.strip().lower() for a in answer_choice.split(',') if a.strip())
        if not answers:
            return EVAL_DOES_NOT_MEET

        intersection = answers & expected_set

        if intersection and answers <= expected_set:
            return EVAL_MEETS
        elif intersection and not is_custom:
            return EVAL_PARTIAL
        else:
            return EVAL_DOES_NOT_MEET
    else:
        answer_lower = answer_choice.lower()

        if answer_lower in expected_set:
            return EVAL_MEETS

        if not is_custom and answer_lower == "partial" and "yes" in expected_set:
            return EVAL_PARTIAL

        return EVAL_DOES_NOT_MEET


def init_db():
    Base.metadata.create_all(bind=engine)


def seed_default_admin():
    """Create a default admin user if no users exist."""
    import bcrypt
    db = SessionLocal()
    try:
        if db.query(User).count() == 0:
            hashed = bcrypt.hashpw("changeme".encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
            admin = User(
                email="admin@example.com",
                display_name="Admin",
                password_hash=hashed,
                role="admin",
                is_active=True,
            )
            db.add(admin)
            db.commit()
    finally:
        db.close()


def seed_question_bank():
    db = SessionLocal()
    default_questions = [
                ("Access Control", "Do you enforce role-based access control (RBAC) for all systems?"),
                ("Access Control", "How do you manage user provisioning and de-provisioning?"),
                ("Access Control", "Do you require multi-factor authentication (MFA) for privileged accounts?"),
                ("Access Control", "How frequently do you review user access permissions?"),
                ("Encryption", "Do you encrypt data at rest using industry-standard algorithms (AES-256)?"),
                ("Encryption", "Do you encrypt data in transit using TLS 1.2 or higher?"),
                ("Encryption", "How do you manage encryption keys and key rotation?"),
                ("Encryption", "Do you use encryption for backup data?"),
                ("Incident Response", "Do you have a documented incident response plan?"),
                ("Incident Response", "How quickly can you detect and respond to security incidents?"),
                ("Incident Response", "Do you conduct post-incident reviews and root cause analysis?"),
                ("Incident Response", "What is your process for notifying affected parties of a data breach?"),
                ("Vulnerability Management", "How frequently do you conduct vulnerability scans?"),
                ("Vulnerability Management", "What is your process for patching critical vulnerabilities?"),
                ("Vulnerability Management", "Do you perform regular penetration testing?"),
                ("Vulnerability Management", "How do you prioritize vulnerability remediation?"),
                ("SOC2", "Have you completed a SOC 2 Type II audit in the past 12 months?"),
                ("SOC2", "Are there any exceptions noted in your most recent SOC 2 report?"),
                ("SOC2", "Do you have ISO 27001 or other security certifications?"),
                ("BC/DR", "Do you have a documented business continuity plan?"),
                ("BC/DR", "What is your Recovery Time Objective (RTO) for critical systems?"),
                ("BC/DR", "How frequently do you test your disaster recovery procedures?"),
                ("BC/DR", "Do you maintain geographically separated backup locations?"),
                ("Vendor Management", "Do you maintain an inventory of all third-party vendors?"),
                ("Vendor Management", "How do you assess the security posture of your vendors?"),
                ("Vendor Management", "Do you require vendors to meet minimum security standards?"),
                ("System Categorization & Impact Assessment", "Do you classify systems and data based on their criticality, sensitivity, and business impact?"),
                ("System Categorization & Impact Assessment", "What types of data does your organization process, store, or have access to (e.g., personal data, financial data, confidential business information)?"),
                ("System Categorization & Impact Assessment", "Do you conduct regular impact or risk assessments for systems handling critical or sensitive data?"),
                ("System Categorization & Impact Assessment", "Do you maintain a comprehensive and up-to-date inventory of all hardware, software, and digital assets?"),
                ("System Categorization & Impact Assessment", "Do you have processes in place to prioritize and protect critical assets within your inventory?"),
                ("System Categorization & Impact Assessment", "Are sensitive or high-impact systems categorized to ensure enhanced security controls are applied?"),
                ("Secure System Design & Architecture", "Do you incorporate security principles into system and application design and architecture?"),
                ("Secure System Design & Architecture", "Are secure development practices embedded throughout your system development lifecycle (SDLC)?"),
                ("Secure System Design & Architecture", "Are systems designed to mitigate vulnerabilities through controls such as segmentation, firewalls, or isolation mechanisms?"),
                ("Secure System Design & Architecture", "Is phishing-resistant multi-factor authentication (MFA) enforced for privileged access or access to sensitive systems?"),
                ("Secure System Design & Architecture", "Can multi-factor authentication (MFA) be enforced for all users, including contractors or third-party users?"),
                ("Secure System Design & Architecture", "Does your system support integration with external identity providers (e.g., SSO providers)?"),
                ("Access Control (Extended)", "Are all users authenticated using unique user accounts (no shared accounts)?"),
                ("Access Control (Extended)", "Does authentication use currently supported, non-deprecated mechanisms?"),
                ("Access Control (Extended)", "Does the application support role-based access control (RBAC) to restrict access to systems and data?"),
                ("Access Control (Extended)", "Does the application support project-, tenant-, or resource-level access controls?"),
                ("Access Control (Extended)", "Can customer administrators provision and deprovision user accounts without vendor assistance?"),
                ("Access Control (Extended)", "Can customer administrators assign or revoke administrative privileges?"),
                ("Access Control (Extended)", "Can customer administrators define and manage RBAC roles without vendor configuration changes?"),
                ("Access Control (Extended)", "Can password complexity requirements be configured within the application?"),
                ("Access Control (Extended)", "For users not authenticated via SSO, are password complexity rules enforced (length, character types, reuse, etc.)?"),
                ("Access Control (Extended)", "Are access permissions reviewed and updated at least annually?"),
                ("Access Control (Extended)", "Does the system support limits on concurrent user sessions?"),
                ("U.S. Citizenship & Legal Residency", "Can you verify U.S. citizenship or legal residency for personnel with administrative access to systems processing customer data?"),
                ("U.S. Citizenship & Legal Residency", "Can access to systems be restricted based on U.S. citizenship or residency requirements?"),
                ("U.S. Citizenship & Legal Residency", "Do you maintain documentation verifying personnel eligibility and access restrictions upon request?"),
                ("Continuous Monitoring", "Do you monitor systems for cybersecurity threats and vulnerabilities on a continuous basis?"),
                ("Continuous Monitoring", "Do you maintain a security operations capability to detect and respond to threats?"),
                ("Continuous Monitoring", "Do you monitor relevant threats, vulnerabilities, and attacker techniques?"),
                ("Continuous Monitoring", "Are vulnerability scans and penetration tests performed regularly?"),
                ("Continuous Monitoring", "Are provisioning and access changes logged?"),
                ("Continuous Monitoring", "Are system, application, and user activities logged for security monitoring?"),
                ("Continuous Monitoring", "Are data movement and modification events logged?"),
                ("Continuous Monitoring", "Are logs available for compliance or audit review?"),
                ("Continuous Monitoring", "Is access to critical systems logged and monitored for anomalies?"),
                ("Continuous Monitoring", "Are logs analyzed using a SIEM or similar tooling?"),
                ("Continuous Monitoring", "Are logs structured for ingestion into customer SIEM tools?"),
                ("Continuous Monitoring", "Does the platform generate application-level audit logs?"),
                ("Continuous Monitoring", "Are logs exportable via API, file transfer, or scheduled delivery?"),
                ("Continuous Monitoring", "What user-level activity is logged for provisioning and privilege changes?"),
                ("Continuous Monitoring", "What is the cadence for log availability (real-time, near-real-time, batch)?"),
                ("Continuous Monitoring", "What mechanisms are supported for log delivery (API, syslog, file transfer)?"),
                ("Continuous Monitoring", "Does the system support event-driven or near-real-time log forwarding?"),
                ("Continuous Monitoring", "Are audit trails maintained for access and data modifications?"),
                ("Continuous Monitoring", "Are authentication events logged and retained for sensitive systems?"),
                ("Continuous Monitoring", "Are privileged account authentication events logged and retained?"),
                ("Incident Response & Reporting", "Are documented incident response procedures in place defining roles, escalation paths, and communication channels?"),
                ("Incident Response & Reporting", "Do incident procedures define timelines for notification and escalation?"),
                ("Incident Response & Reporting", "Are incidents involving sensitive or regulated data escalated promptly?"),
                ("Incident Response & Reporting", "Have you experienced a data breach in the past two years, and was it remediated?"),
                ("Incident Response & Reporting", "Are customers notified within a defined timeframe following incidents impacting their data or services?"),
                ("Risk & Compliance Assessment", "Do you conduct cybersecurity risk assessments regularly?"),
                ("Risk & Compliance Assessment", "Are risk assessments aligned with recognized frameworks (e.g., NIST, ISO)?"),
                ("Risk & Compliance Assessment", "Are remediation timelines defined based on risk severity?"),
                ("Risk & Compliance Assessment", "Do you verify remediation completion through testing or validation?"),
                ("Risk & Compliance Assessment", "Are third-party vulnerability assessments or penetration tests conducted?"),
                ("Risk & Compliance Assessment", "Are vendors included within your risk assessment process?"),
                ("Backup & Recovery", "Are backups performed for all critical systems storing customer data?"),
                ("Backup & Recovery", "Is backup data encrypted using strong encryption?"),
                ("Backup & Recovery", "Is backup data stored separately from production systems?"),
                ("Backup & Recovery", "What RTO and RPO targets are defined for restoring customer access and data?"),
                ("Backup & Recovery", "Are disaster recovery and restoration procedures tested at least annually?"),
                ("Backup & Recovery", "Is customer data included in disaster recovery and business continuity plans?"),
                ("Backup & Recovery", "Have you experienced major business disruptions, and how were they addressed?"),
                ("Backup & Recovery", "Do you use a third-party disaster recovery service provider?"),
                ("Configuration Management", "Do you maintain configuration baselines for critical systems?"),
                ("Configuration Management", "Are unauthorized configuration changes detected and prevented?"),
                ("Configuration Management", "Are default credentials removed or updated on deployed systems?"),
                ("Configuration Management", "Is a formal change management or change control process in place?"),
                ("Security Control Lifecycle Management", "Are security controls regularly reviewed and updated?"),
                ("Security Control Lifecycle Management", "Are controls tailored to meet customer or regulatory requirements?"),
                ("Security Control Lifecycle Management", "Are independent audits conducted to validate control effectiveness?"),
                ("Security Control Lifecycle Management", "Are changes to controls documented for audit purposes?"),
                ("Security Control Lifecycle Management", "Are controls securely decommissioned when no longer needed?"),
                ("Data Protection & Standard Encryption", "Is sensitive data encrypted at rest and in transit using strong encryption?"),
                ("Data Protection & Standard Encryption", "Are encryption keys securely managed and protected?"),
                ("Data Protection & Standard Encryption", "Are data flows restricted to authorized systems and personnel?"),
                ("Data Protection & Standard Encryption", "Is customer data stored only in approved geographic regions?"),
                ("Data Protection & Standard Encryption", "If stored outside approved regions, are safeguards in place?"),
                ("Data Protection & Standard Encryption", "Is confidential data protected using file- or folder-level encryption?"),
                ("Data Protection & Standard Encryption", "Are logical or physical controls in place to segregate customer data?"),
                ("Data Protection & Standard Encryption", "Who is your primary cloud service provider?"),
                ("Data Protection & Standard Encryption", "Can customers confirm where their data is stored?"),
                ("Information Classification", "Do you classify data based on sensitivity or regulatory requirements?"),
                ("Information Classification", "Are classification labels communicated to personnel?"),
                ("Information Classification", "Are handling requirements enforced based on classification?"),
                ("Information Classification", "Are classifications reviewed and updated periodically?"),
                ("Cybersecurity Governance", "Are cybersecurity leadership roles and responsibilities formally defined?"),
                ("Cybersecurity Governance", "Are security policies documented, published, and enforced?"),
                ("Cybersecurity Governance", "Are policies aligned with recognized frameworks (NIST, ISO, CIS)?"),
                ("Cybersecurity Governance", "Are audits conducted to validate compliance?"),
                ("Cybersecurity Governance", "What password strength requirements are enforced?"),
                ("Cybersecurity Governance", "Is there a documented and enforced password policy?"),
                ("Cybersecurity Governance", "Is password reuse prevented?"),
                ("Cybersecurity Governance", "Is there a patch management policy or process?"),
                ("Advanced Encryption", "Is strong encryption (e.g., AES-256) used for sensitive or regulated data?"),
                ("Advanced Encryption", "Are encryption keys rotated according to policy?"),
                ("Advanced Encryption", "Do you support customer-managed encryption keys (BYOK / CMK)?"),
                ("Advanced Encryption", "Is access to encrypted data logged and monitored?"),
                ("Third-Party Risk Management", "Do you assess cybersecurity risks for third-party vendors?"),
                ("Third-Party Risk Management", "Are vendors required to meet defined security standards?"),
                ("Third-Party Risk Management", "Are subcontractors required to meet equivalent security requirements?"),
                ("Third-Party Risk Management", "Do contracts require vendors to report security incidents within defined timeframes?"),
                ("Third-Party Risk Management", "Are processes in place to manage and remediate third-party security incidents?"),
                ("Training & Security Awareness", "Do employees receive role-based cybersecurity training?"),
                ("Training & Security Awareness", "Is security awareness training conducted at least annually?"),
                ("Training & Security Awareness", "Are employees trained on applicable regulatory or compliance requirements?"),
                ("Training & Security Awareness", "Is security awareness reinforced through ongoing activities such as phishing simulations?"),
                ("Physical & Environmental Security", "Are physical access controls in place to secure facilities and systems?"),
                ("Physical & Environmental Security", "Are physical security measures used to enforce least-privilege access?"),
                ("Physical & Environmental Security", "Is physical access to critical infrastructure monitored and logged?"),
                ("Physical & Environmental Security", "Are environmental controls in place to protect systems (fire suppression, temperature, power)?"),
                ("AI Governance & Data Control", "Is customer data used to train or improve AI models?"),
                ("AI Governance & Data Control", "Do you support masking, redaction, or tokenization of sensitive data prior to AI processing?"),
                ("AI Governance & Data Control", "Can customers restrict the types of data submitted to AI features?"),
                ("AI Governance & Data Control", "Are AI feature usage logs available for audit or SIEM ingestion?"),
                ("AI Governance & Data Control", "Where are AI models hosted and where is customer data processed?"),
                ("AI Governance & Data Control", "What controls protect access to AI models and customer data?"),
                ("AI Governance & Data Control", "Can AI features be disabled or restricted by the customer?"),
    ]
    try:
        if db.query(QuestionBankItem).count() == 0:
            for category, text in default_questions:
                item = QuestionBankItem(category=category, text=text, is_active=True)
                db.add(item)
            db.commit()
        else:
            existing_texts = set(q.text for q in db.query(QuestionBankItem).all())
            added = 0
            for category, text in default_questions:
                if text not in existing_texts:
                    item = QuestionBankItem(category=category, text=text, is_active=True)
                    db.add(item)
                    added += 1
            if added > 0:
                db.commit()
    finally:
        db.close()


def seed_risk_statements():
    db = SessionLocal()
    seed_data = [
        # Access Control
        ("Access Control", TRIGGER_CATEGORY_HAS_DNM, SEVERITY_HIGH,
         "Vendor fails to meet access control requirements. Unauthorized access to systems and data may not be adequately prevented, increasing risk of data breach or privilege escalation.",
         "Vendor must implement role-based access control (RBAC), enforce multi-factor authentication for privileged accounts, and establish a user access review process. Provide evidence of implementation within 60 days."),
        ("Access Control", TRIGGER_CATEGORY_SCORE_BELOW_50, SEVERITY_CRITICAL,
         "Vendor access control posture is critically deficient. Multiple access control requirements are unmet, indicating systemic gaps in identity and access management.",
         "Vendor must conduct a comprehensive access control gap assessment and submit a remediation plan within 30 days. All critical gaps must be resolved within 90 days with independent verification."),

        # Encryption
        ("Encryption", TRIGGER_CATEGORY_HAS_DNM, SEVERITY_CRITICAL,
         "Vendor fails to meet encryption requirements. Data at rest or in transit may not be adequately protected, exposing sensitive information to interception or unauthorized access.",
         "Vendor must implement AES-256 encryption at rest and TLS 1.2+ in transit within 30 days. Provide documentation of encryption standards and key management procedures."),
        ("Encryption", TRIGGER_PARTIAL_HIGH_CRITICAL, SEVERITY_HIGH,
         "Vendor partially meets encryption requirements on critical controls. Encryption key management or backup encryption may have gaps requiring attention.",
         "Vendor must address encryption gaps identified in the assessment. Submit an encryption improvement plan within 45 days and complete implementation within 90 days."),

        # Incident Response
        ("Incident Response", TRIGGER_CATEGORY_HAS_DNM, SEVERITY_HIGH,
         "Vendor lacks adequate incident response capabilities. Without documented procedures and defined response timelines, security incidents may go undetected or unresolved.",
         "Vendor must establish a documented incident response plan with defined roles, escalation paths, and notification timelines. Provide the plan for review within 45 days."),
        ("Incident Response", TRIGGER_CATEGORY_SCORE_BELOW_50, SEVERITY_CRITICAL,
         "Vendor incident response posture is critically deficient. Multiple incident response requirements are unmet, indicating inability to detect, respond to, or recover from security incidents.",
         "Vendor must engage qualified security personnel to develop and implement a comprehensive incident response program within 60 days. Include tabletop exercises and provide evidence of readiness."),

        # Vulnerability Management
        ("Vulnerability Management", TRIGGER_CATEGORY_HAS_DNM, SEVERITY_HIGH,
         "Vendor does not meet vulnerability management requirements. Unpatched vulnerabilities may exist in production systems, increasing exposure to known exploits.",
         "Vendor must implement regular vulnerability scanning (at minimum monthly) and establish a patch management process with defined SLAs. Provide scan results and remediation timelines within 30 days."),
        ("Vulnerability Management", TRIGGER_PARTIAL_HIGH_CRITICAL, SEVERITY_MEDIUM,
         "Vendor partially meets critical vulnerability management controls. Penetration testing or vulnerability prioritization processes may have gaps.",
         "Vendor must address gaps in vulnerability management practices. Submit evidence of penetration testing and a vulnerability prioritization framework within 60 days."),

        # SOC2
        ("SOC2", TRIGGER_CATEGORY_HAS_DNM, SEVERITY_HIGH,
         "Vendor lacks current SOC 2 Type II certification or has noted exceptions. Independent assurance of security controls cannot be verified.",
         "Vendor must obtain SOC 2 Type II certification or provide equivalent independent audit evidence. Submit a timeline for audit completion within 30 days."),
        ("SOC2", TRIGGER_CATEGORY_SCORE_BELOW_50, SEVERITY_CRITICAL,
         "Vendor compliance posture is critically deficient. Lack of SOC 2 or equivalent certifications indicates insufficient third-party validation of security controls.",
         "Vendor must engage an accredited audit firm and provide a SOC 2 Type II audit plan within 45 days. Consider alternative compensating controls in the interim."),

        # BC/DR
        ("BC/DR", TRIGGER_CATEGORY_HAS_DNM, SEVERITY_HIGH,
         "Vendor does not meet business continuity and disaster recovery requirements. Service availability and data recovery capabilities may be inadequate.",
         "Vendor must establish documented BC/DR plans with defined RTO/RPO targets. Provide plans and evidence of testing within 60 days."),
        ("BC/DR", TRIGGER_PARTIAL_HIGH_CRITICAL, SEVERITY_MEDIUM,
         "Vendor partially meets critical business continuity controls. DR testing frequency or geographic separation of backups may be insufficient.",
         "Vendor must address BC/DR gaps and provide evidence of annual DR testing and geographically separated backup locations within 90 days."),

        # Vendor Management
        ("Vendor Management", TRIGGER_CATEGORY_HAS_DNM, SEVERITY_MEDIUM,
         "Vendor does not meet third-party vendor management requirements. Supply chain risk may not be adequately managed or monitored.",
         "Vendor must establish a vendor inventory and assessment program. Provide documentation of vendor risk management procedures within 60 days."),
        ("Vendor Management", TRIGGER_CATEGORY_SCORE_BELOW_50, SEVERITY_HIGH,
         "Vendor's own third-party risk management is critically deficient. Cascading supply chain risks are not being identified or mitigated.",
         "Vendor must implement a formal third-party risk management program including vendor assessments and minimum security standards. Submit program documentation within 45 days."),

        # System Categorization & Impact Assessment
        ("System Categorization & Impact Assessment", TRIGGER_CATEGORY_HAS_DNM, SEVERITY_MEDIUM,
         "Vendor does not adequately classify systems and data based on criticality and sensitivity. Without proper categorization, security controls may not be proportionate to risk.",
         "Vendor must implement a data classification and system categorization framework. Provide documentation of classification standards and asset inventory within 60 days."),
        ("System Categorization & Impact Assessment", TRIGGER_CATEGORY_SCORE_BELOW_50, SEVERITY_HIGH,
         "Vendor system categorization and impact assessment processes are critically deficient. Lack of asset inventory and risk assessment indicates fundamental gaps in security governance.",
         "Vendor must conduct a comprehensive asset inventory and impact assessment within 45 days. Classify all systems handling customer data and apply appropriate controls."),

        # Secure System Design & Architecture
        ("Secure System Design & Architecture", TRIGGER_CATEGORY_HAS_DNM, SEVERITY_HIGH,
         "Vendor does not meet secure system design requirements. Systems may lack fundamental security controls such as segmentation, secure SDLC practices, or phishing-resistant MFA.",
         "Vendor must incorporate security-by-design principles into system architecture and development lifecycle. Submit a secure architecture review and remediation plan within 45 days."),
        ("Secure System Design & Architecture", TRIGGER_PARTIAL_HIGH_CRITICAL, SEVERITY_MEDIUM,
         "Vendor partially meets critical secure design controls. MFA enforcement or SSO integration capabilities may have gaps.",
         "Vendor must address secure design gaps, particularly around MFA and identity provider integration. Provide an improvement plan within 60 days."),

        # Access Control (Extended)
        ("Access Control (Extended)", TRIGGER_CATEGORY_HAS_DNM, SEVERITY_HIGH,
         "Vendor does not meet extended access control requirements. Shared accounts, inadequate RBAC, or inability for customer self-service user management creates security and operational risk.",
         "Vendor must eliminate shared accounts, implement configurable RBAC, and enable customer-managed user provisioning. Provide a remediation timeline within 30 days."),
        ("Access Control (Extended)", TRIGGER_CATEGORY_SCORE_BELOW_50, SEVERITY_CRITICAL,
         "Vendor extended access control posture is critically deficient. Multiple access management capabilities are missing, preventing adequate customer control over user access.",
         "Vendor must conduct a comprehensive access control capability assessment and deliver a remediation plan within 30 days. All critical gaps must be addressed within 90 days."),

        # U.S. Citizenship & Legal Residency
        ("U.S. Citizenship & Legal Residency", TRIGGER_CATEGORY_HAS_DNM, SEVERITY_HIGH,
         "Vendor cannot verify U.S. citizenship or legal residency for personnel with administrative access to customer data. This may violate regulatory or contractual requirements.",
         "Vendor must implement personnel eligibility verification processes and access restriction controls. Provide documentation of compliance within 30 days."),

        # Continuous Monitoring
        ("Continuous Monitoring", TRIGGER_CATEGORY_HAS_DNM, SEVERITY_HIGH,
         "Vendor does not meet continuous monitoring requirements. Security events may not be detected, logged, or analyzed, reducing visibility into potential threats.",
         "Vendor must implement continuous security monitoring including SIEM integration, audit logging, and anomaly detection. Provide a monitoring architecture document within 45 days."),
        ("Continuous Monitoring", TRIGGER_CATEGORY_SCORE_BELOW_50, SEVERITY_CRITICAL,
         "Vendor continuous monitoring posture is critically deficient. Widespread gaps in logging, monitoring, and audit capabilities indicate inability to detect or respond to security events.",
         "Vendor must implement a comprehensive security monitoring program within 60 days. Include SIEM deployment, log aggregation, and real-time alerting for critical systems."),
        ("Continuous Monitoring", TRIGGER_PARTIAL_HIGH_CRITICAL, SEVERITY_MEDIUM,
         "Vendor partially meets critical continuous monitoring controls. Log delivery mechanisms, SIEM integration, or audit trail completeness may have gaps.",
         "Vendor must address monitoring gaps, particularly around log export capabilities and audit trail completeness. Submit improvement plan within 60 days."),

        # Incident Response & Reporting
        ("Incident Response & Reporting", TRIGGER_CATEGORY_HAS_DNM, SEVERITY_HIGH,
         "Vendor does not meet incident response and reporting requirements. Incident notification timelines, escalation procedures, or breach history disclosure may be inadequate.",
         "Vendor must establish documented incident response and notification procedures with defined timelines. Provide updated procedures within 30 days."),
        ("Incident Response & Reporting", TRIGGER_CATEGORY_SCORE_BELOW_50, SEVERITY_CRITICAL,
         "Vendor incident response and reporting capabilities are critically deficient. Lack of documented procedures and unclear notification commitments present significant risk.",
         "Vendor must engage qualified incident response resources and establish a comprehensive incident management program within 45 days."),

        # Risk & Compliance Assessment
        ("Risk & Compliance Assessment", TRIGGER_CATEGORY_HAS_DNM, SEVERITY_MEDIUM,
         "Vendor does not meet risk and compliance assessment requirements. Regular risk assessments may not be conducted or may not align with recognized frameworks.",
         "Vendor must implement a risk assessment program aligned with NIST or ISO frameworks. Provide evidence of most recent risk assessment within 45 days."),
        ("Risk & Compliance Assessment", TRIGGER_PARTIAL_HIGH_CRITICAL, SEVERITY_MEDIUM,
         "Vendor partially meets critical risk and compliance controls. Remediation validation or third-party assessment processes may have gaps.",
         "Vendor must address gaps in risk assessment validation and remediation tracking. Submit evidence of improvement within 60 days."),

        # Backup & Recovery
        ("Backup & Recovery", TRIGGER_CATEGORY_HAS_DNM, SEVERITY_HIGH,
         "Vendor does not meet backup and recovery requirements. Customer data may not be adequately backed up, encrypted, or recoverable in the event of a disaster.",
         "Vendor must implement encrypted backups with defined RTO/RPO targets, separated from production systems. Provide backup architecture documentation within 30 days."),
        ("Backup & Recovery", TRIGGER_CATEGORY_SCORE_BELOW_50, SEVERITY_CRITICAL,
         "Vendor backup and recovery posture is critically deficient. Multiple backup and DR requirements are unmet, indicating high risk of data loss during an incident.",
         "Vendor must implement a comprehensive backup and recovery program within 45 days. Include encryption, geographic separation, and annual DR testing."),

        # Configuration Management
        ("Configuration Management", TRIGGER_CATEGORY_HAS_DNM, SEVERITY_MEDIUM,
         "Vendor does not meet configuration management requirements. Unauthorized configuration changes may go undetected, and default credentials may remain in production systems.",
         "Vendor must implement configuration baselines, change detection, and formal change management processes. Provide evidence within 60 days."),
        ("Configuration Management", TRIGGER_CATEGORY_SCORE_BELOW_50, SEVERITY_HIGH,
         "Vendor configuration management practices are critically deficient. Lack of baselines, change control, and credential management creates significant vulnerability exposure.",
         "Vendor must establish configuration management standards and change control processes within 45 days. Remove all default credentials immediately."),

        # Security Control Lifecycle Management
        ("Security Control Lifecycle Management", TRIGGER_CATEGORY_HAS_DNM, SEVERITY_MEDIUM,
         "Vendor does not meet security control lifecycle management requirements. Controls may not be regularly reviewed, audited, or updated to address evolving threats.",
         "Vendor must implement a control lifecycle management process including periodic review, independent audit, and documented change tracking. Provide evidence within 60 days."),

        # Data Protection & Standard Encryption
        ("Data Protection & Standard Encryption", TRIGGER_CATEGORY_HAS_DNM, SEVERITY_CRITICAL,
         "Vendor does not meet data protection requirements. Sensitive data may lack encryption, data flows may not be restricted, or data residency requirements may not be met.",
         "Vendor must implement comprehensive data protection controls including encryption at rest and in transit, data flow restrictions, and data residency compliance within 30 days."),
        ("Data Protection & Standard Encryption", TRIGGER_CATEGORY_SCORE_BELOW_50, SEVERITY_CRITICAL,
         "Vendor data protection posture is critically deficient. Multiple data protection requirements are unmet, indicating high risk of unauthorized data exposure.",
         "Vendor must conduct a data protection gap assessment and implement remediation within 30 days. Prioritize encryption, data segregation, and geographic controls."),

        # Information Classification
        ("Information Classification", TRIGGER_CATEGORY_HAS_DNM, SEVERITY_MEDIUM,
         "Vendor does not meet information classification requirements. Data may not be properly classified, labeled, or handled according to sensitivity levels.",
         "Vendor must implement a data classification scheme with handling requirements. Provide classification policy and evidence of implementation within 60 days."),

        # Cybersecurity Governance
        ("Cybersecurity Governance", TRIGGER_CATEGORY_HAS_DNM, SEVERITY_HIGH,
         "Vendor does not meet cybersecurity governance requirements. Security policies may not be documented, published, or aligned with recognized frameworks.",
         "Vendor must establish formal cybersecurity governance with documented policies aligned to NIST or ISO frameworks. Provide policy documentation within 45 days."),
        ("Cybersecurity Governance", TRIGGER_CATEGORY_SCORE_BELOW_50, SEVERITY_CRITICAL,
         "Vendor cybersecurity governance is critically deficient. Lack of policies, leadership accountability, and framework alignment indicates fundamental gaps in security program maturity.",
         "Vendor must engage qualified security leadership and establish a formal cybersecurity governance program within 45 days. Align policies with recognized frameworks and enforce password/patch management."),

        # Advanced Encryption
        ("Advanced Encryption", TRIGGER_CATEGORY_HAS_DNM, SEVERITY_HIGH,
         "Vendor does not meet advanced encryption requirements. Key rotation, customer-managed keys, or encryption monitoring capabilities may be missing.",
         "Vendor must address advanced encryption gaps including key rotation policies and BYOK/CMK support. Provide a remediation plan within 45 days."),
        ("Advanced Encryption", TRIGGER_PARTIAL_HIGH_CRITICAL, SEVERITY_MEDIUM,
         "Vendor partially meets critical advanced encryption controls. Customer-managed key support or encryption access logging may have gaps.",
         "Vendor must address advanced encryption gaps and provide a timeline for BYOK/CMK support and encryption audit logging within 60 days."),

        # Third-Party Risk Management
        ("Third-Party Risk Management", TRIGGER_CATEGORY_HAS_DNM, SEVERITY_HIGH,
         "Vendor does not meet third-party risk management requirements. Subcontractor security, vendor incident reporting, and supply chain risk may not be adequately managed.",
         "Vendor must implement a third-party risk management program covering subcontractors and supply chain. Provide program documentation and incident reporting procedures within 45 days."),
        ("Third-Party Risk Management", TRIGGER_CATEGORY_SCORE_BELOW_50, SEVERITY_CRITICAL,
         "Vendor third-party risk management is critically deficient. Supply chain risks are not being identified, assessed, or mitigated, creating cascading risk exposure.",
         "Vendor must establish a comprehensive third-party risk program within 45 days including vendor assessments, contractual security requirements, and incident notification obligations."),

        # Training & Security Awareness
        ("Training & Security Awareness", TRIGGER_CATEGORY_HAS_DNM, SEVERITY_MEDIUM,
         "Vendor does not meet security training and awareness requirements. Employees may not receive adequate cybersecurity training, increasing risk of human-factor security incidents.",
         "Vendor must implement annual role-based security awareness training with phishing simulations. Provide training records and program documentation within 60 days."),

        # Physical & Environmental Security
        ("Physical & Environmental Security", TRIGGER_CATEGORY_HAS_DNM, SEVERITY_MEDIUM,
         "Vendor does not meet physical and environmental security requirements. Physical access to critical systems may not be adequately controlled or monitored.",
         "Vendor must implement physical access controls, monitoring, and environmental protections for critical infrastructure. Provide evidence of controls within 60 days."),

        # AI Governance & Data Control
        ("AI Governance & Data Control", TRIGGER_CATEGORY_HAS_DNM, SEVERITY_HIGH,
         "Vendor does not meet AI governance and data control requirements. Customer data may be used for AI model training, or AI features may lack adequate controls and audit logging.",
         "Vendor must provide clear documentation on AI data usage, implement customer controls for AI features, and enable AI audit logging. Address gaps within 45 days."),
        ("AI Governance & Data Control", TRIGGER_PARTIAL_HIGH_CRITICAL, SEVERITY_MEDIUM,
         "Vendor partially meets critical AI governance controls. Data masking, customer opt-out, or AI audit capabilities may have gaps.",
         "Vendor must address AI governance gaps including data protection controls and customer configurability. Provide improvement plan within 60 days."),
    ]
    try:
        existing = set()
        for rs in db.query(RiskStatement).all():
            existing.add((rs.category, rs.trigger_condition, rs.finding_text))

        added = 0
        for category, trigger, severity, finding, remediation in seed_data:
            if (category, trigger, finding) not in existing:
                db.add(RiskStatement(
                    category=category,
                    trigger_condition=trigger,
                    severity=severity,
                    finding_text=finding,
                    remediation_text=remediation,
                    is_active=True,
                ))
                added += 1
        if added > 0:
            db.commit()
    finally:
        db.close()


def backfill_question_categories():
    """Backfill categories on assessment questions by matching text to question bank."""
    db = SessionLocal()
    try:
        uncategorized = db.query(Question).filter(
            (Question.category == None) | (Question.category == "")
        ).all()
        if not uncategorized:
            return

        bank_map = {item.text: item.category for item in db.query(QuestionBankItem).all()}

        updated = 0
        for q in uncategorized:
            cat = bank_map.get(q.question_text)
            if cat:
                q.category = cat
                updated += 1

        if updated > 0:
            db.commit()
    finally:
        db.close()


def backfill_question_bank_item_ids():
    """Backfill question_bank_item_id on assessment questions by matching text to question bank."""
    db = SessionLocal()
    try:
        unlinked = db.query(Question).filter(
            Question.question_bank_item_id == None
        ).all()
        if not unlinked:
            return

        bank_map = {item.text: item.id for item in db.query(QuestionBankItem).all()}

        updated = 0
        for q in unlinked:
            bank_id = bank_map.get(q.question_text)
            if bank_id:
                q.question_bank_item_id = bank_id
                updated += 1

        if updated > 0:
            db.commit()
    finally:
        db.close()


def backfill_decision_scores():
    """Backfill overall_score on finalized decisions that don't have one yet."""
    from app.services.scoring import compute_assessment_scores

    db = SessionLocal()
    try:
        decisions = db.query(AssessmentDecision).filter(
            AssessmentDecision.status == DECISION_STATUS_FINAL,
            AssessmentDecision.overall_score == None
        ).all()
        if not decisions:
            return

        updated = 0
        for decision in decisions:
            questions = db.query(Question).filter(
                Question.assessment_id == decision.assessment_id
            ).order_by(Question.order).all()
            response = db.query(Response).filter(
                Response.assessment_id == decision.assessment_id,
                Response.status == RESPONSE_STATUS_SUBMITTED
            ).order_by(Response.submitted_at.desc()).first()

            if questions and response:
                scores = compute_assessment_scores(questions, response)
                if scores.get("overall_score") is not None:
                    decision.overall_score = int(scores["overall_score"])
                    updated += 1

        if updated > 0:
            db.commit()
    finally:
        db.close()


def backfill_vendor_new_columns():
    """Add new vendor columns to existing database using raw ALTER TABLE.
    New tables (vendor_contacts, vendor_documents) are auto-created by init_db().
    """
    import sqlite3
    conn = sqlite3.connect("./questionnaires.db")
    cursor = conn.cursor()

    new_columns = [
        ("industry", "VARCHAR(100)"),
        ("website", "VARCHAR(500)"),
        ("headquarters", "VARCHAR(255)"),
        ("service_type", "VARCHAR(50)"),
        ("data_classification", "VARCHAR(50)"),
        ("business_criticality", "VARCHAR(20)"),
        ("access_level", "VARCHAR(50)"),
        ("inherent_risk_tier", "VARCHAR(20)"),
        ("tier_override", "VARCHAR(20)"),
        ("tier_notes", "TEXT"),
        ("contract_start_date", "DATETIME"),
        ("contract_end_date", "DATETIME"),
        ("contract_value", "VARCHAR(100)"),
        ("auto_renewal", "BOOLEAN DEFAULT 0"),
    ]

    cursor.execute("PRAGMA table_info(vendors)")
    existing = {row[1] for row in cursor.fetchall()}

    for col_name, col_type in new_columns:
        if col_name not in existing:
            try:
                cursor.execute(f"ALTER TABLE vendors ADD COLUMN {col_name} {col_type}")
            except sqlite3.OperationalError:
                pass

    # Also backfill assessment_decisions table
    cursor.execute("PRAGMA table_info(assessment_decisions)")
    existing_decision_cols = {row[1] for row in cursor.fetchall()}
    if "overall_score" not in existing_decision_cols:
        try:
            cursor.execute("ALTER TABLE assessment_decisions ADD COLUMN overall_score INTEGER")
        except sqlite3.OperationalError:
            pass

    # Also backfill assessments table
    cursor.execute("PRAGMA table_info(assessments)")
    existing_assessment_cols = {row[1] for row in cursor.fetchall()}
    if "previous_assessment_id" not in existing_assessment_cols:
        try:
            cursor.execute("ALTER TABLE assessments ADD COLUMN previous_assessment_id INTEGER")
        except sqlite3.OperationalError:
            pass
    for col_name, col_type in [("sent_to_email", "VARCHAR(255)"), ("expires_at", "DATETIME"), ("reminders_paused", "BOOLEAN DEFAULT 0"), ("first_reminder_days", "INTEGER"), ("reminder_frequency_days", "INTEGER"), ("max_reminders", "INTEGER")]:
        if col_name not in existing_assessment_cols:
            try:
                cursor.execute(f"ALTER TABLE assessments ADD COLUMN {col_name} {col_type}")
            except sqlite3.OperationalError:
                pass

    conn.commit()
    conn.close()


# ==================== VENDOR ACTIVITY TIMELINE ====================

ACTIVITY_VENDOR_CREATED = "VENDOR_CREATED"
ACTIVITY_ASSESSMENT_CREATED = "ASSESSMENT_CREATED"
ACTIVITY_ASSESSMENT_SENT = "ASSESSMENT_SENT"
ACTIVITY_REMINDER_SENT = "REMINDER_SENT"
ACTIVITY_VENDOR_SUBMITTED = "VENDOR_SUBMITTED"
ACTIVITY_DECISION_FINALIZED = "DECISION_FINALIZED"
ACTIVITY_TIER_CHANGED = "TIER_CHANGED"
ACTIVITY_ONBOARDING_COMPLETE = "ONBOARDING_COMPLETE"
ACTIVITY_ANALYST_ASSIGNED = "ANALYST_ASSIGNED"

ACTIVITY_ICONS = {
    ACTIVITY_VENDOR_CREATED: "bi-building",
    ACTIVITY_ASSESSMENT_CREATED: "bi-clipboard-plus",
    ACTIVITY_ASSESSMENT_SENT: "bi-envelope-paper",
    ACTIVITY_REMINDER_SENT: "bi-bell",
    ACTIVITY_VENDOR_SUBMITTED: "bi-check2-circle",
    ACTIVITY_DECISION_FINALIZED: "bi-shield-check",
    ACTIVITY_TIER_CHANGED: "bi-arrow-left-right",
    ACTIVITY_ONBOARDING_COMPLETE: "bi-magic",
    ACTIVITY_ANALYST_ASSIGNED: "bi-person-check",
}

ACTIVITY_COLORS = {
    ACTIVITY_VENDOR_CREATED: "#6c757d",
    ACTIVITY_ASSESSMENT_CREATED: "#0d6efd",
    ACTIVITY_ASSESSMENT_SENT: "#6f42c1",
    ACTIVITY_REMINDER_SENT: "#fd7e14",
    ACTIVITY_VENDOR_SUBMITTED: "#198754",
    ACTIVITY_DECISION_FINALIZED: "#0dcaf0",
    ACTIVITY_TIER_CHANGED: "#ffc107",
    ACTIVITY_ONBOARDING_COMPLETE: "#6f42c1",
    ACTIVITY_ANALYST_ASSIGNED: "#0d6efd",
}


class VendorActivity(Base):
    __tablename__ = "vendor_activities"

    id = Column(Integer, primary_key=True, index=True)
    vendor_id = Column(Integer, ForeignKey("vendors.id"), nullable=False)
    activity_type = Column(String(50), nullable=False)
    description = Column(Text, nullable=False)
    assessment_id = Column(Integer, ForeignKey("assessments.id"), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    metadata_json = Column(Text, nullable=True)

    vendor = relationship("Vendor")
    user = relationship("User", foreign_keys=[user_id])


# ==================== NOTIFICATIONS ====================

NOTIF_ASSESSMENT_SUBMITTED = "ASSESSMENT_SUBMITTED"
NOTIF_ESCALATION = "ESCALATION"
NOTIF_ONBOARDING_COMPLETE = "ONBOARDING_COMPLETE"
NOTIF_ANALYST_ASSIGNED = "ANALYST_ASSIGNED"
NOTIF_DECISION_FINALIZED = "DECISION_FINALIZED"
NOTIF_REMEDIATION_OVERDUE = "REMEDIATION_OVERDUE"
NOTIF_DOCUMENT_EXPIRING = "DOCUMENT_EXPIRING"
NOTIF_COMMENT_ADDED = "COMMENT_ADDED"

NOTIF_ICONS = {
    NOTIF_ASSESSMENT_SUBMITTED: "bi-inbox-fill",
    NOTIF_ESCALATION: "bi-exclamation-triangle-fill",
    NOTIF_ONBOARDING_COMPLETE: "bi-magic",
    NOTIF_ANALYST_ASSIGNED: "bi-person-check",
    NOTIF_DECISION_FINALIZED: "bi-shield-check",
    NOTIF_REMEDIATION_OVERDUE: "bi-clock-history",
    NOTIF_DOCUMENT_EXPIRING: "bi-file-earmark-excel",
    NOTIF_COMMENT_ADDED: "bi-chat-left-text",
}


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    notification_type = Column(String(50), nullable=False)
    message = Column(Text, nullable=False)
    link = Column(String(500), nullable=True)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    vendor_id = Column(Integer, ForeignKey("vendors.id"), nullable=True)
    assessment_id = Column(Integer, ForeignKey("assessments.id"), nullable=True)


# ==================== INTERNAL COMMENTS ====================

COMMENT_ENTITY_VENDOR = "vendor"
COMMENT_ENTITY_ASSESSMENT = "assessment"
COMMENT_ENTITY_DECISION = "decision"
COMMENT_ENTITY_REMEDIATION = "remediation"
COMMENT_ENTITY_CONTROL = "control"
COMMENT_ENTITY_CONTROL_IMPL = "control_implementation"
VALID_COMMENT_ENTITIES = [COMMENT_ENTITY_VENDOR, COMMENT_ENTITY_ASSESSMENT, COMMENT_ENTITY_DECISION, COMMENT_ENTITY_REMEDIATION, COMMENT_ENTITY_CONTROL, COMMENT_ENTITY_CONTROL_IMPL]


class Comment(Base):
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True, index=True)
    entity_type = Column(String(50), nullable=False, index=True)
    entity_id = Column(Integer, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    body = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User")


# ==================== SCORING CONFIGURATION ====================

class ScoringConfig(Base):
    """DB-backed scoring thresholds. Single-row table."""
    __tablename__ = "scoring_config"

    id = Column(Integer, primary_key=True, index=True)
    very_low_min = Column(Integer, default=90)
    low_min = Column(Integer, default=70)
    moderate_min = Column(Integer, default=50)
    high_min = Column(Integer, default=30)
    # Below high_min → VERY_HIGH
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


def ensure_scoring_config(db_session):
    """Ensure a default ScoringConfig row exists."""
    config = db_session.query(ScoringConfig).first()
    if not config:
        config = ScoringConfig()
        db_session.add(config)
        db_session.commit()
    return config


# ==================== TIERING RULES ====================

class TieringRule(Base):
    """Configurable tiering rules. Each row is a condition→tier mapping."""
    __tablename__ = "tiering_rules"

    id = Column(Integer, primary_key=True, index=True)
    field = Column(String(50), nullable=False)  # data_classification, business_criticality, access_level
    value = Column(String(50), nullable=False)   # e.g. "Restricted", "Critical"
    tier = Column(String(20), nullable=False)     # "Tier 1", "Tier 2", "Tier 3"
    priority = Column(Integer, default=0)         # lower = checked first
    created_at = Column(DateTime, default=datetime.utcnow)


def seed_default_tiering_rules():
    """Seed the default tiering rules if none exist."""
    db = SessionLocal()
    try:
        if db.query(TieringRule).count() > 0:
            return
        defaults = [
            ("data_classification", "Restricted", "Tier 1", 0),
            ("business_criticality", "Critical", "Tier 1", 1),
            ("data_classification", "Confidential", "Tier 2", 2),
            ("business_criticality", "High", "Tier 2", 3),
            ("access_level", "Extensive", "Tier 2", 4),
        ]
        for field, value, tier, priority in defaults:
            db.add(TieringRule(field=field, value=value, tier=tier, priority=priority))
        db.commit()
    finally:
        db.close()


# ==================== RISK SNAPSHOT (HISTORICAL TRENDS) ====================

class RiskSnapshot(Base):
    """Point-in-time risk snapshot for trend analysis."""
    __tablename__ = "risk_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    vendor_id = Column(Integer, ForeignKey("vendors.id"), nullable=False)
    assessment_id = Column(Integer, ForeignKey("assessments.id"), nullable=True)
    decision_id = Column(Integer, ForeignKey("assessment_decisions.id"), nullable=True)
    overall_score = Column(Integer, nullable=True)
    risk_rating = Column(String(20), nullable=True)
    decision_outcome = Column(String(30), nullable=True)
    snapshot_date = Column(DateTime, default=datetime.utcnow)

    vendor = relationship("Vendor")


# ==================== VENDOR OFFBOARDING ====================

VENDOR_STATUS_OFFBOARDING = "OFFBOARDING"
VALID_VENDOR_STATUSES = [VENDOR_STATUS_ACTIVE, VENDOR_STATUS_ARCHIVED, VENDOR_STATUS_OFFBOARDING]


# ==================== RISK EXCEPTION / WAIVER ====================

EXCEPTION_STATUS_PENDING = "PENDING"
EXCEPTION_STATUS_APPROVED = "APPROVED"
EXCEPTION_STATUS_REJECTED = "REJECTED"
EXCEPTION_STATUS_EXPIRED = "EXPIRED"
VALID_EXCEPTION_STATUSES = [EXCEPTION_STATUS_PENDING, EXCEPTION_STATUS_APPROVED, EXCEPTION_STATUS_REJECTED, EXCEPTION_STATUS_EXPIRED]

ACTIVITY_EXCEPTION_CREATED = "EXCEPTION_CREATED"
ACTIVITY_EXCEPTION_APPROVED = "EXCEPTION_APPROVED"
NOTIF_EXCEPTION_REQUESTED = "EXCEPTION_REQUESTED"
NOTIF_EXCEPTION_APPROVED = "EXCEPTION_APPROVED"


class RiskException(Base):
    __tablename__ = "risk_exceptions"

    id = Column(Integer, primary_key=True, index=True)
    vendor_id = Column(Integer, ForeignKey("vendors.id"), nullable=False)
    assessment_id = Column(Integer, ForeignKey("assessments.id"), nullable=True)
    decision_id = Column(Integer, ForeignKey("assessment_decisions.id"), nullable=True)
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    risk_accepted = Column(Text, nullable=True)
    justification = Column(Text, nullable=True)
    status = Column(String(20), default=EXCEPTION_STATUS_PENDING, nullable=False)
    expires_at = Column(DateTime, nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    approved_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    vendor = relationship("Vendor")
    assessment = relationship("Assessment")
    decision = relationship("AssessmentDecision")
    created_by = relationship("User", foreign_keys=[created_by_id])
    approved_by = relationship("User", foreign_keys=[approved_by_id])


# ==================== VENDOR INTAKE REQUEST ====================

INTAKE_STATUS_PENDING = "PENDING"
INTAKE_STATUS_APPROVED = "APPROVED"
INTAKE_STATUS_REJECTED = "REJECTED"
INTAKE_STATUS_CONVERTED = "CONVERTED"
VALID_INTAKE_STATUSES = [INTAKE_STATUS_PENDING, INTAKE_STATUS_APPROVED, INTAKE_STATUS_REJECTED, INTAKE_STATUS_CONVERTED]

VALID_INTAKE_URGENCIES = ["LOW", "MEDIUM", "HIGH"]

NOTIF_INTAKE_SUBMITTED = "INTAKE_SUBMITTED"
NOTIF_INTAKE_APPROVED = "INTAKE_APPROVED"
NOTIF_INTAKE_REJECTED = "INTAKE_REJECTED"
NOTIF_APPROVAL_REQUESTED = "APPROVAL_REQUESTED"
NOTIF_DECISION_APPROVED = "DECISION_APPROVED"


class VendorIntakeRequest(Base):
    __tablename__ = "vendor_intake_requests"

    id = Column(Integer, primary_key=True, index=True)
    requested_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    vendor_name = Column(String(255), nullable=False)
    business_justification = Column(Text, nullable=True)
    department = Column(String(255), nullable=True)
    service_description = Column(Text, nullable=True)
    data_types_shared = Column(Text, nullable=True)
    estimated_contract_value = Column(String(100), nullable=True)
    urgency = Column(String(20), default="MEDIUM", nullable=False)
    status = Column(String(20), default=INTAKE_STATUS_PENDING, nullable=False)
    reviewed_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    review_notes = Column(Text, nullable=True)
    vendor_id = Column(Integer, ForeignKey("vendors.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    requested_by = relationship("User", foreign_keys=[requested_by_id])
    reviewed_by = relationship("User", foreign_keys=[reviewed_by_id])
    vendor = relationship("Vendor")


def backfill_new_feature_columns():
    """Add columns for offboarding, comments, scoring config, etc."""
    import sqlite3
    conn = sqlite3.connect("./questionnaires.db")
    cursor = conn.cursor()

    # Vendor: offboarding_checklist
    cursor.execute("PRAGMA table_info(vendors)")
    vendor_cols = {row[1] for row in cursor.fetchall()}
    if "offboarding_checklist" not in vendor_cols:
        try:
            cursor.execute("ALTER TABLE vendors ADD COLUMN offboarding_checklist TEXT")
        except sqlite3.OperationalError:
            pass

    conn.commit()
    conn.close()


def backfill_approval_columns():
    """Add multi-approver columns to assessment_decisions."""
    import sqlite3
    conn = sqlite3.connect("./questionnaires.db")
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(assessment_decisions)")
    existing = {row[1] for row in cursor.fetchall()}
    for col_name, col_type in [
        ("requires_approval", "BOOLEAN DEFAULT 0"),
        ("approval_status", "VARCHAR(20)"),
        ("approved_by_id", "INTEGER"),
        ("approval_notes", "TEXT"),
        ("approved_at", "DATETIME"),
    ]:
        if col_name not in existing:
            try:
                cursor.execute(f"ALTER TABLE assessment_decisions ADD COLUMN {col_name} {col_type}")
            except sqlite3.OperationalError:
                pass

    # framework_ref on question_bank_items
    cursor.execute("PRAGMA table_info(question_bank_items)")
    qbi_cols = {row[1] for row in cursor.fetchall()}
    if "framework_ref" not in qbi_cols:
        try:
            cursor.execute("ALTER TABLE question_bank_items ADD COLUMN framework_ref VARCHAR(255)")
        except sqlite3.OperationalError:
            pass

    conn.commit()
    conn.close()


def backfill_auth_columns():
    """Add auth-related columns to existing tables."""
    import sqlite3
    conn = sqlite3.connect("./questionnaires.db")
    cursor = conn.cursor()

    # Vendor: assigned_analyst_id
    cursor.execute("PRAGMA table_info(vendors)")
    vendor_cols = {row[1] for row in cursor.fetchall()}
    if "assigned_analyst_id" not in vendor_cols:
        try:
            cursor.execute("ALTER TABLE vendors ADD COLUMN assigned_analyst_id INTEGER")
        except sqlite3.OperationalError:
            pass

    # VendorActivity: user_id
    cursor.execute("PRAGMA table_info(vendor_activities)")
    activity_cols = {row[1] for row in cursor.fetchall()}
    if "user_id" not in activity_cols:
        try:
            cursor.execute("ALTER TABLE vendor_activities ADD COLUMN user_id INTEGER")
        except sqlite3.OperationalError:
            pass

    # AssessmentDecision: decided_by_id
    cursor.execute("PRAGMA table_info(assessment_decisions)")
    decision_cols = {row[1] for row in cursor.fetchall()}
    if "decided_by_id" not in decision_cols:
        try:
            cursor.execute("ALTER TABLE assessment_decisions ADD COLUMN decided_by_id INTEGER")
        except sqlite3.OperationalError:
            pass

    # RemediationItem: assigned_to_user_id
    cursor.execute("PRAGMA table_info(remediation_items)")
    rem_cols = {row[1] for row in cursor.fetchall()}
    if "assigned_to_user_id" not in rem_cols:
        try:
            cursor.execute("ALTER TABLE remediation_items ADD COLUMN assigned_to_user_id INTEGER")
        except sqlite3.OperationalError:
            pass

    # Assessment: assigned_analyst_id
    cursor.execute("PRAGMA table_info(assessments)")
    assessment_cols = {row[1] for row in cursor.fetchall()}
    if "assigned_analyst_id" not in assessment_cols:
        try:
            cursor.execute("ALTER TABLE assessments ADD COLUMN assigned_analyst_id INTEGER")
        except sqlite3.OperationalError:
            pass

    conn.commit()
    conn.close()


def backfill_template_columns():
    """Add suggested_tier column to assessment_templates for existing DBs."""
    import sqlite3
    conn = sqlite3.connect("./questionnaires.db")
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(assessment_templates)")
    existing = {row[1] for row in cursor.fetchall()}
    if "suggested_tier" not in existing:
        try:
            cursor.execute("ALTER TABLE assessment_templates ADD COLUMN suggested_tier VARCHAR(20)")
        except sqlite3.OperationalError:
            pass
    conn.commit()
    conn.close()


def seed_default_templates():
    """Create 3 seed templates from the question bank if no templates exist."""
    import secrets
    db = SessionLocal()
    try:
        if db.query(AssessmentTemplate).count() > 0:
            return

        bank_items = db.query(QuestionBankItem).filter(
            QuestionBankItem.is_active == True
        ).order_by(QuestionBankItem.category, QuestionBankItem.id).all()

        if not bank_items:
            return

        # Group by category
        categories = {}
        for item in bank_items:
            categories.setdefault(item.category, []).append(item)

        # Tier 1: Comprehensive — all questions, HIGH weight
        t1 = AssessmentTemplate(
            name="Comprehensive Security Assessment",
            description="Full-depth assessment covering all security domains. Recommended for Tier 1 (Critical Risk) vendors with access to restricted data or critical business functions.",
            token=secrets.token_hex(32),
            suggested_tier="Tier 1",
        )
        db.add(t1)
        db.flush()
        order = 0
        for cat, items in categories.items():
            for item in items:
                db.add(TemplateQuestion(
                    template_id=t1.id,
                    question_text=item.text,
                    order=order,
                    weight="HIGH",
                    category=cat,
                    answer_options=item.answer_options,
                ))
                order += 1

        # Tier 2: Standard — core categories, 2 per category, MEDIUM weight
        core_categories = [
            "Access Control", "Encryption", "Incident Response",
            "Vulnerability Management", "SOC2", "BC/DR",
            "Data Protection & Standard Encryption", "Continuous Monitoring",
            "Cybersecurity Governance", "Backup & Recovery",
        ]
        t2 = AssessmentTemplate(
            name="Standard Vendor Review",
            description="Balanced assessment covering core security domains. Recommended for Tier 2 (Elevated Risk) vendors.",
            token=secrets.token_hex(32),
            suggested_tier="Tier 2",
        )
        db.add(t2)
        db.flush()
        order = 0
        for cat in core_categories:
            items = categories.get(cat, [])
            for item in items[:2]:
                db.add(TemplateQuestion(
                    template_id=t2.id,
                    question_text=item.text,
                    order=order,
                    weight="MEDIUM",
                    category=cat,
                    answer_options=item.answer_options,
                ))
                order += 1

        # Tier 3: Lightweight — essential categories, 2 per category, LOW weight
        essential_categories = [
            "Access Control", "Encryption", "Incident Response",
            "SOC2", "BC/DR",
        ]
        t3 = AssessmentTemplate(
            name="Lightweight Vendor Screening",
            description="Quick screening covering essential security basics. Recommended for Tier 3 (Standard Risk) vendors.",
            token=secrets.token_hex(32),
            suggested_tier="Tier 3",
        )
        db.add(t3)
        db.flush()
        order = 0
        for cat in essential_categories:
            items = categories.get(cat, [])
            for item in items[:2]:
                db.add(TemplateQuestion(
                    template_id=t3.id,
                    question_text=item.text,
                    order=order,
                    weight="LOW",
                    category=cat,
                    answer_options=item.answer_options,
                ))
                order += 1

        db.commit()
    finally:
        db.close()


# ==================== AUDIT LOG ====================

AUDIT_ACTION_CREATE = "CREATE"
AUDIT_ACTION_UPDATE = "UPDATE"
AUDIT_ACTION_DELETE = "DELETE"
AUDIT_ACTION_STATUS_CHANGE = "STATUS_CHANGE"
VALID_AUDIT_ACTIONS = [AUDIT_ACTION_CREATE, AUDIT_ACTION_UPDATE, AUDIT_ACTION_DELETE, AUDIT_ACTION_STATUS_CHANGE]

AUDIT_ENTITY_VENDOR = "vendor"
AUDIT_ENTITY_ASSESSMENT = "assessment"
AUDIT_ENTITY_DECISION = "decision"
AUDIT_ENTITY_REMEDIATION = "remediation"
AUDIT_ENTITY_EXCEPTION = "exception"
AUDIT_ENTITY_USER = "user"
AUDIT_ENTITY_SCORING_CONFIG = "scoring_config"
AUDIT_ENTITY_TIERING_RULE = "tiering_rule"
AUDIT_ENTITY_REMINDER_CONFIG = "reminder_config"
AUDIT_ENTITY_SLA_CONFIG = "sla_config"
AUDIT_ENTITY_CONTROL = "control"
AUDIT_ENTITY_CONTROL_IMPL = "control_implementation"


class AuditLog(Base):
    """Append-only audit trail for compliance."""
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    actor_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    actor_email = Column(String(255), nullable=True)
    action = Column(String(50), nullable=False, index=True)
    entity_type = Column(String(50), nullable=False, index=True)
    entity_id = Column(Integer, nullable=True, index=True)
    entity_label = Column(String(500), nullable=True)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)

    actor = relationship("User", foreign_keys=[actor_user_id])


# ==================== SLA CONFIGURATION ====================

SLA_STATUS_ON_TRACK = "ON_TRACK"
SLA_STATUS_AT_RISK = "AT_RISK"
SLA_STATUS_BREACHED = "BREACHED"
SLA_STATUS_COMPLETED = "COMPLETED"
SLA_STATUS_NA = "N/A"

SLA_STATUS_COLORS = {
    SLA_STATUS_ON_TRACK: "#198754",
    SLA_STATUS_AT_RISK: "#fd7e14",
    SLA_STATUS_BREACHED: "#dc3545",
    SLA_STATUS_COMPLETED: "#6c757d",
    SLA_STATUS_NA: "#adb5bd",
}

SLA_STATUS_LABELS = {
    SLA_STATUS_ON_TRACK: "On Track",
    SLA_STATUS_AT_RISK: "At Risk",
    SLA_STATUS_BREACHED: "Breached",
    SLA_STATUS_COMPLETED: "Completed",
    SLA_STATUS_NA: "N/A",
}

ACTIVITY_SLA_WARNING = "SLA_WARNING"
ACTIVITY_SLA_BREACH = "SLA_BREACH"
NOTIF_SLA_WARNING = "SLA_WARNING"
NOTIF_SLA_BREACH = "SLA_BREACH"

# Add SLA activity icons/colors
ACTIVITY_ICONS[ACTIVITY_SLA_WARNING] = "bi-clock-history"
ACTIVITY_ICONS[ACTIVITY_SLA_BREACH] = "bi-exclamation-octagon-fill"
ACTIVITY_COLORS[ACTIVITY_SLA_WARNING] = "#fd7e14"
ACTIVITY_COLORS[ACTIVITY_SLA_BREACH] = "#dc3545"
NOTIF_ICONS[NOTIF_SLA_WARNING] = "bi-clock-history"
NOTIF_ICONS[NOTIF_SLA_BREACH] = "bi-exclamation-octagon-fill"


class SLAConfig(Base):
    """Per-tier SLA targets. One row per tier."""
    __tablename__ = "sla_configs"

    id = Column(Integer, primary_key=True, index=True)
    tier = Column(String(20), unique=True, nullable=False)
    response_deadline_days = Column(Integer, nullable=False, default=14)
    review_deadline_days = Column(Integer, nullable=False, default=7)
    warning_threshold_pct = Column(Integer, nullable=False, default=80)
    enabled = Column(Boolean, default=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


def ensure_sla_configs(db_session):
    """Seed default SLA configs if none exist."""
    existing = db_session.query(SLAConfig).count()
    if existing > 0:
        return db_session.query(SLAConfig).order_by(SLAConfig.tier).all()

    defaults = [
        ("Tier 1", 14, 7, 80),
        ("Tier 2", 21, 14, 80),
        ("Tier 3", 30, 21, 80),
    ]
    configs = []
    for tier, resp_days, rev_days, warn_pct in defaults:
        cfg = SLAConfig(
            tier=tier,
            response_deadline_days=resp_days,
            review_deadline_days=rev_days,
            warning_threshold_pct=warn_pct,
            enabled=True,
        )
        db_session.add(cfg)
        configs.append(cfg)
    db_session.commit()
    return configs


def backfill_sla_columns():
    """Add sla_enabled column to reminder_config for existing DBs."""
    import sqlite3
    conn = sqlite3.connect("./questionnaires.db")
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(reminder_config)")
    existing = {row[1] for row in cursor.fetchall()}
    if "sla_enabled" not in existing:
        try:
            cursor.execute("ALTER TABLE reminder_config ADD COLUMN sla_enabled BOOLEAN DEFAULT 1")
        except sqlite3.OperationalError:
            pass
    conn.commit()
    conn.close()


def backfill_onboarding_column():
    """Add onboarding_dismissed column to users for existing DBs."""
    import sqlite3
    conn = sqlite3.connect("./questionnaires.db")
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(users)")
    existing = {row[1] for row in cursor.fetchall()}
    if "onboarding_dismissed" not in existing:
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN onboarding_dismissed BOOLEAN DEFAULT 0")
        except sqlite3.OperationalError:
            pass
    conn.commit()
    conn.close()


# ==================== CONTROLS MODULE ====================

# Control type constants
CONTROL_TYPE_PREVENTIVE = "PREVENTIVE"
CONTROL_TYPE_DETECTIVE = "DETECTIVE"
CONTROL_TYPE_CORRECTIVE = "CORRECTIVE"
VALID_CONTROL_TYPES = [CONTROL_TYPE_PREVENTIVE, CONTROL_TYPE_DETECTIVE, CONTROL_TYPE_CORRECTIVE]
CONTROL_TYPE_LABELS = {
    CONTROL_TYPE_PREVENTIVE: "Preventive",
    CONTROL_TYPE_DETECTIVE: "Detective",
    CONTROL_TYPE_CORRECTIVE: "Corrective",
}

CONTROL_IMPL_MANUAL = "MANUAL"
CONTROL_IMPL_AUTOMATED = "AUTOMATED"
CONTROL_IMPL_HYBRID = "HYBRID"
VALID_CONTROL_IMPL_TYPES = [CONTROL_IMPL_MANUAL, CONTROL_IMPL_AUTOMATED, CONTROL_IMPL_HYBRID]
CONTROL_IMPL_TYPE_LABELS = {
    CONTROL_IMPL_MANUAL: "Manual",
    CONTROL_IMPL_AUTOMATED: "Automated",
    CONTROL_IMPL_HYBRID: "Hybrid",
}

VALID_CONTROL_CRITICALITIES = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]

CONTROL_FREQ_CONTINUOUS = "CONTINUOUS"
CONTROL_FREQ_DAILY = "DAILY"
CONTROL_FREQ_WEEKLY = "WEEKLY"
CONTROL_FREQ_MONTHLY = "MONTHLY"
CONTROL_FREQ_QUARTERLY = "QUARTERLY"
CONTROL_FREQ_SEMI_ANNUAL = "SEMI_ANNUAL"
CONTROL_FREQ_ANNUAL = "ANNUAL"
VALID_CONTROL_FREQUENCIES = [
    CONTROL_FREQ_CONTINUOUS, CONTROL_FREQ_DAILY, CONTROL_FREQ_WEEKLY,
    CONTROL_FREQ_MONTHLY, CONTROL_FREQ_QUARTERLY, CONTROL_FREQ_SEMI_ANNUAL,
    CONTROL_FREQ_ANNUAL,
]
CONTROL_FREQUENCY_LABELS = {
    CONTROL_FREQ_CONTINUOUS: "Continuous",
    CONTROL_FREQ_DAILY: "Daily",
    CONTROL_FREQ_WEEKLY: "Weekly",
    CONTROL_FREQ_MONTHLY: "Monthly",
    CONTROL_FREQ_QUARTERLY: "Quarterly",
    CONTROL_FREQ_SEMI_ANNUAL: "Semi-Annual",
    CONTROL_FREQ_ANNUAL: "Annual",
}
CONTROL_FREQUENCY_DAYS = {
    CONTROL_FREQ_CONTINUOUS: 1,
    CONTROL_FREQ_DAILY: 1,
    CONTROL_FREQ_WEEKLY: 7,
    CONTROL_FREQ_MONTHLY: 30,
    CONTROL_FREQ_QUARTERLY: 90,
    CONTROL_FREQ_SEMI_ANNUAL: 182,
    CONTROL_FREQ_ANNUAL: 365,
}

VALID_CONTROL_DOMAINS = [
    "Access Control",
    "Asset Management",
    "Business Continuity",
    "Change Management",
    "Cryptography",
    "Data Protection",
    "Governance",
    "Human Resources",
    "Incident Management",
    "Network Security",
    "Physical Security",
    "Risk Management",
    "Secure Development",
    "Security Monitoring",
    "Security Operations",
    "Third-Party Management",
    "Training & Awareness",
    "Vulnerability Management",
]

# Implementation status
IMPL_STATUS_NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
IMPL_STATUS_PLANNED = "PLANNED"
IMPL_STATUS_PARTIAL = "PARTIAL"
IMPL_STATUS_IMPLEMENTED = "IMPLEMENTED"
IMPL_STATUS_NOT_APPLICABLE = "NOT_APPLICABLE"
VALID_IMPL_STATUSES = [
    IMPL_STATUS_NOT_IMPLEMENTED, IMPL_STATUS_PLANNED, IMPL_STATUS_PARTIAL,
    IMPL_STATUS_IMPLEMENTED, IMPL_STATUS_NOT_APPLICABLE,
]
IMPL_STATUS_LABELS = {
    IMPL_STATUS_NOT_IMPLEMENTED: "Not Implemented",
    IMPL_STATUS_PLANNED: "Planned",
    IMPL_STATUS_PARTIAL: "Partial",
    IMPL_STATUS_IMPLEMENTED: "Implemented",
    IMPL_STATUS_NOT_APPLICABLE: "N/A",
}
IMPL_STATUS_COLORS = {
    IMPL_STATUS_NOT_IMPLEMENTED: "#dc3545",
    IMPL_STATUS_PLANNED: "#6f42c1",
    IMPL_STATUS_PARTIAL: "#fd7e14",
    IMPL_STATUS_IMPLEMENTED: "#198754",
    IMPL_STATUS_NOT_APPLICABLE: "#6c757d",
}

# Effectiveness
EFFECTIVENESS_NONE = "NONE"
EFFECTIVENESS_INEFFECTIVE = "INEFFECTIVE"
EFFECTIVENESS_PARTIALLY_EFFECTIVE = "PARTIALLY_EFFECTIVE"
EFFECTIVENESS_LARGELY_EFFECTIVE = "LARGELY_EFFECTIVE"
EFFECTIVENESS_EFFECTIVE = "EFFECTIVE"
VALID_EFFECTIVENESS_LEVELS = [
    EFFECTIVENESS_NONE, EFFECTIVENESS_INEFFECTIVE,
    EFFECTIVENESS_PARTIALLY_EFFECTIVE, EFFECTIVENESS_LARGELY_EFFECTIVE,
    EFFECTIVENESS_EFFECTIVE,
]
EFFECTIVENESS_LABELS = {
    EFFECTIVENESS_NONE: "None",
    EFFECTIVENESS_INEFFECTIVE: "Ineffective",
    EFFECTIVENESS_PARTIALLY_EFFECTIVE: "Partially Effective",
    EFFECTIVENESS_LARGELY_EFFECTIVE: "Largely Effective",
    EFFECTIVENESS_EFFECTIVE: "Effective",
}
EFFECTIVENESS_COLORS = {
    EFFECTIVENESS_NONE: "#6c757d",
    EFFECTIVENESS_INEFFECTIVE: "#dc3545",
    EFFECTIVENESS_PARTIALLY_EFFECTIVE: "#fd7e14",
    EFFECTIVENESS_LARGELY_EFFECTIVE: "#0dcaf0",
    EFFECTIVENESS_EFFECTIVE: "#198754",
}

# Test type / result
TEST_TYPE_DESIGN = "DESIGN"
TEST_TYPE_OPERATING = "OPERATING"
VALID_TEST_TYPES = [TEST_TYPE_DESIGN, TEST_TYPE_OPERATING]
TEST_TYPE_LABELS = {TEST_TYPE_DESIGN: "Design", TEST_TYPE_OPERATING: "Operating"}

TEST_RESULT_PASS = "PASS"
TEST_RESULT_FAIL = "FAIL"
TEST_RESULT_PARTIAL = "PARTIAL"
TEST_RESULT_NOT_TESTED = "NOT_TESTED"
VALID_TEST_RESULTS = [TEST_RESULT_PASS, TEST_RESULT_FAIL, TEST_RESULT_PARTIAL, TEST_RESULT_NOT_TESTED]
TEST_RESULT_LABELS = {
    TEST_RESULT_PASS: "Pass",
    TEST_RESULT_FAIL: "Fail",
    TEST_RESULT_PARTIAL: "Partial",
    TEST_RESULT_NOT_TESTED: "Not Tested",
}
TEST_RESULT_COLORS = {
    TEST_RESULT_PASS: "#198754",
    TEST_RESULT_FAIL: "#dc3545",
    TEST_RESULT_PARTIAL: "#fd7e14",
    TEST_RESULT_NOT_TESTED: "#6c757d",
}

# Test status
TEST_STATUS_SCHEDULED = "SCHEDULED"
TEST_STATUS_IN_PROGRESS = "IN_PROGRESS"
TEST_STATUS_COMPLETED = "COMPLETED"
VALID_TEST_STATUSES = [TEST_STATUS_SCHEDULED, TEST_STATUS_IN_PROGRESS, TEST_STATUS_COMPLETED]
TEST_STATUS_LABELS = {
    TEST_STATUS_SCHEDULED: "Scheduled",
    TEST_STATUS_IN_PROGRESS: "In Progress",
    TEST_STATUS_COMPLETED: "Completed",
}
TEST_STATUS_COLORS = {
    TEST_STATUS_SCHEDULED: "#6c757d",
    TEST_STATUS_IN_PROGRESS: "#0d6efd",
    TEST_STATUS_COMPLETED: "#198754",
}

# Finding risk rating (for control tests)
FINDING_RISK_LOW = "LOW"
FINDING_RISK_MEDIUM = "MEDIUM"
FINDING_RISK_HIGH = "HIGH"
FINDING_RISK_CRITICAL = "CRITICAL"
FINDING_RISK_NONE = "NONE"
VALID_FINDING_RISK_RATINGS = [FINDING_RISK_NONE, FINDING_RISK_LOW, FINDING_RISK_MEDIUM, FINDING_RISK_HIGH, FINDING_RISK_CRITICAL]
FINDING_RISK_LABELS = {
    FINDING_RISK_NONE: "No Finding", FINDING_RISK_LOW: "Low",
    FINDING_RISK_MEDIUM: "Medium", FINDING_RISK_HIGH: "High",
    FINDING_RISK_CRITICAL: "Critical",
}
FINDING_RISK_COLORS = {
    FINDING_RISK_NONE: "#198754", FINDING_RISK_LOW: "#0dcaf0",
    FINDING_RISK_MEDIUM: "#fd7e14", FINDING_RISK_HIGH: "#ffc107",
    FINDING_RISK_CRITICAL: "#dc3545",
}

# Control finding type/status constants (for ControlFinding model)
FINDING_TYPE_DESIGN = "DESIGN_DEFICIENCY"
FINDING_TYPE_OPERATING = "OPERATING_DEFICIENCY"
VALID_FINDING_TYPES = [FINDING_TYPE_DESIGN, FINDING_TYPE_OPERATING]
FINDING_TYPE_LABELS = {FINDING_TYPE_DESIGN: "Design Deficiency", FINDING_TYPE_OPERATING: "Operating Deficiency"}

FINDING_STATUS_OPEN = "OPEN"
FINDING_STATUS_IN_PROGRESS = "IN_PROGRESS"
FINDING_STATUS_REMEDIATED = "REMEDIATED"
FINDING_STATUS_CLOSED = "CLOSED"
VALID_FINDING_STATUSES = [FINDING_STATUS_OPEN, FINDING_STATUS_IN_PROGRESS, FINDING_STATUS_REMEDIATED, FINDING_STATUS_CLOSED]
FINDING_STATUS_LABELS = {FINDING_STATUS_OPEN: "Open", FINDING_STATUS_IN_PROGRESS: "In Progress", FINDING_STATUS_REMEDIATED: "Remediated", FINDING_STATUS_CLOSED: "Closed"}
FINDING_STATUS_COLORS = {FINDING_STATUS_OPEN: "#dc3545", FINDING_STATUS_IN_PROGRESS: "#fd7e14", FINDING_STATUS_REMEDIATED: "#0dcaf0", FINDING_STATUS_CLOSED: "#198754"}

# Activity / notification constants for controls
ACTIVITY_CONTROL_IMPL_UPDATED = "CONTROL_IMPL_UPDATED"
ACTIVITY_ICONS[ACTIVITY_CONTROL_IMPL_UPDATED] = "bi-shield-lock"
ACTIVITY_COLORS[ACTIVITY_CONTROL_IMPL_UPDATED] = "#6f42c1"

NOTIF_CONTROL_TEST_OVERDUE = "CONTROL_TEST_OVERDUE"
NOTIF_ICONS[NOTIF_CONTROL_TEST_OVERDUE] = "bi-shield-exclamation"


class Control(Base):
    __tablename__ = "controls"

    id = Column(Integer, primary_key=True, index=True)
    control_ref = Column(String(50), unique=True, nullable=False, index=True)
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    domain = Column(String(100), nullable=False, index=True)
    control_type = Column(String(20), nullable=False, default=CONTROL_TYPE_PREVENTIVE)
    implementation_type = Column(String(20), nullable=False, default=CONTROL_IMPL_MANUAL)
    test_frequency = Column(String(20), nullable=False, default=CONTROL_FREQ_ANNUAL)
    criticality = Column(String(20), nullable=False, default="MEDIUM")
    owner_role = Column(String(100), nullable=True)
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    objective = Column(Text, nullable=True)
    procedure = Column(Text, nullable=True)
    operation_frequency = Column(String(20), nullable=True)
    default_test_procedure = Column(Text, nullable=True)
    evidence_instructions = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    framework_mappings = relationship("ControlFrameworkMapping", back_populates="control", cascade="all, delete-orphan")
    question_mappings = relationship("ControlQuestionMapping", back_populates="control", cascade="all, delete-orphan")
    risk_mappings = relationship("ControlRiskMapping", back_populates="control", cascade="all, delete-orphan")
    implementations = relationship("ControlImplementation", back_populates="control", cascade="all, delete-orphan")
    owner = relationship("User", foreign_keys=[owner_user_id])


class ControlFrameworkMapping(Base):
    __tablename__ = "control_framework_mappings"

    id = Column(Integer, primary_key=True, index=True)
    control_id = Column(Integer, ForeignKey("controls.id"), nullable=False)
    framework = Column(String(50), nullable=False)
    reference = Column(String(100), nullable=False)

    control = relationship("Control", back_populates="framework_mappings")


class ControlQuestionMapping(Base):
    __tablename__ = "control_question_mappings"

    id = Column(Integer, primary_key=True, index=True)
    control_id = Column(Integer, ForeignKey("controls.id"), nullable=False)
    question_bank_item_id = Column(Integer, ForeignKey("question_bank_items.id"), nullable=False)

    control = relationship("Control", back_populates="question_mappings")
    question_bank_item = relationship("QuestionBankItem")


class ControlRiskMapping(Base):
    __tablename__ = "control_risk_mappings"

    id = Column(Integer, primary_key=True, index=True)
    control_id = Column(Integer, ForeignKey("controls.id"), nullable=False)
    risk_statement_id = Column(Integer, ForeignKey("risk_statements.id"), nullable=False)

    control = relationship("Control", back_populates="risk_mappings")
    risk_statement = relationship("RiskStatement")


class ControlImplementation(Base):
    __tablename__ = "control_implementations"

    id = Column(Integer, primary_key=True, index=True)
    control_id = Column(Integer, ForeignKey("controls.id"), nullable=False)
    vendor_id = Column(Integer, ForeignKey("vendors.id"), nullable=True)
    status = Column(String(30), default=IMPL_STATUS_NOT_IMPLEMENTED, nullable=False)
    effectiveness = Column(String(30), default=EFFECTIVENESS_NONE, nullable=False)
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    notes = Column(Text, nullable=True)
    implemented_date = Column(DateTime, nullable=True)
    next_test_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    control = relationship("Control", back_populates="implementations")
    vendor = relationship("Vendor")
    owner = relationship("User", foreign_keys=[owner_user_id])
    tests = relationship("ControlTest", back_populates="implementation", cascade="all, delete-orphan")


class ControlTest(Base):
    __tablename__ = "control_tests"

    id = Column(Integer, primary_key=True, index=True)
    implementation_id = Column(Integer, ForeignKey("control_implementations.id"), nullable=False)
    test_type = Column(String(20), nullable=False, default=TEST_TYPE_OPERATING)
    test_procedure = Column(Text, nullable=True)
    tester_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    test_date = Column(DateTime, default=datetime.utcnow)
    result = Column(String(20), nullable=False, default=TEST_RESULT_NOT_TESTED)
    status = Column(String(20), default=TEST_STATUS_COMPLETED, nullable=False)
    scheduled_date = Column(DateTime, nullable=True)
    findings = Column(Text, nullable=True)
    recommendations = Column(Text, nullable=True)
    test_period_start = Column(DateTime, nullable=True)
    test_period_end = Column(DateTime, nullable=True)
    sample_size = Column(Integer, nullable=True)
    population_size = Column(Integer, nullable=True)
    exceptions_count = Column(Integer, nullable=True, default=0)
    exception_details = Column(Text, nullable=True)
    conclusion = Column(Text, nullable=True)
    finding_risk_rating = Column(String(20), nullable=True)
    reviewer_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    review_date = Column(DateTime, nullable=True)
    review_notes = Column(Text, nullable=True)
    is_roll_forward = Column(Boolean, default=False)
    parent_test_id = Column(Integer, ForeignKey("control_tests.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    implementation = relationship("ControlImplementation", back_populates="tests")
    parent_test = relationship("ControlTest", remote_side="ControlTest.id", uselist=False)
    tester = relationship("User", foreign_keys=[tester_user_id])
    reviewer = relationship("User", foreign_keys=[reviewer_user_id])
    evidence_files = relationship("ControlEvidence", back_populates="test", cascade="all, delete-orphan")


class ControlEvidence(Base):
    __tablename__ = "control_evidence"

    id = Column(Integer, primary_key=True, index=True)
    test_id = Column(Integer, ForeignKey("control_tests.id"), nullable=True)
    original_filename = Column(String(255), nullable=False)
    stored_filename = Column(String(255), nullable=False)
    stored_path = Column(String(512), nullable=False)
    content_type = Column(String(100), nullable=True)
    size_bytes = Column(Integer, nullable=True)
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    implementation_id = Column(Integer, ForeignKey("control_implementations.id"), nullable=True)
    framework_tags = Column(Text, nullable=True)  # JSON list of framework keys this evidence satisfies

    test = relationship("ControlTest", back_populates="evidence_files")
    implementation = relationship("ControlImplementation", foreign_keys=[implementation_id])


class ControlFinding(Base):
    __tablename__ = "control_findings"

    id = Column(Integer, primary_key=True, index=True)
    control_test_id = Column(Integer, ForeignKey("control_tests.id"), nullable=False)
    finding_type = Column(String(30), default=FINDING_TYPE_OPERATING, nullable=False)
    severity = Column(String(20), default="MEDIUM", nullable=False)
    status = Column(String(20), default=FINDING_STATUS_OPEN, nullable=False)
    criteria = Column(Text, nullable=True)       # What should be (the standard)
    condition = Column(Text, nullable=True)       # What is (the finding)
    cause = Column(Text, nullable=True)           # Why the gap exists
    effect = Column(Text, nullable=True)          # Impact/risk of the finding
    recommendation = Column(Text, nullable=True)
    remediation_item_id = Column(Integer, ForeignKey("remediation_items.id"), nullable=True)
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    due_date = Column(DateTime, nullable=True)
    closed_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    test = relationship("ControlTest", backref="control_findings")
    remediation_item = relationship("RemediationItem")
    owner = relationship("User", foreign_keys=[owner_user_id])


# ==================== CONTROL ATTESTATION ====================

ATTESTATION_STATUS_PENDING = "PENDING"
ATTESTATION_STATUS_ATTESTED = "ATTESTED"
ATTESTATION_STATUS_REJECTED = "REJECTED"
ATTESTATION_STATUS_EXPIRED = "EXPIRED"
VALID_ATTESTATION_STATUSES = [ATTESTATION_STATUS_PENDING, ATTESTATION_STATUS_ATTESTED, ATTESTATION_STATUS_REJECTED, ATTESTATION_STATUS_EXPIRED]
ATTESTATION_STATUS_LABELS = {
    ATTESTATION_STATUS_PENDING: "Pending",
    ATTESTATION_STATUS_ATTESTED: "Attested",
    ATTESTATION_STATUS_REJECTED: "Rejected",
    ATTESTATION_STATUS_EXPIRED: "Expired",
}
ATTESTATION_STATUS_COLORS = {
    ATTESTATION_STATUS_PENDING: "#fd7e14",
    ATTESTATION_STATUS_ATTESTED: "#198754",
    ATTESTATION_STATUS_REJECTED: "#dc3545",
    ATTESTATION_STATUS_EXPIRED: "#6c757d",
}


class ControlAttestation(Base):
    __tablename__ = "control_attestations"

    id = Column(Integer, primary_key=True, index=True)
    implementation_id = Column(Integer, ForeignKey("control_implementations.id"), nullable=False)
    attestor_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(String(20), default=ATTESTATION_STATUS_PENDING, nullable=False)
    is_effective = Column(Boolean, nullable=True)  # True=effective, False=not effective, None=not yet attested
    notes = Column(Text, nullable=True)
    evidence_notes = Column(Text, nullable=True)  # Description of evidence supporting attestation
    requested_date = Column(DateTime, default=datetime.utcnow)
    due_date = Column(DateTime, nullable=True)
    attested_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    implementation = relationship("ControlImplementation", backref="attestations")
    attestor = relationship("User", foreign_keys=[attestor_user_id])


# ==================== CONTROL HEALTH SNAPSHOT ====================

class ControlHealthSnapshot(Base):
    """Point-in-time health score snapshot for trend analysis."""
    __tablename__ = "control_health_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    implementation_id = Column(Integer, ForeignKey("control_implementations.id"), nullable=False)
    health_score = Column(Integer, nullable=False)
    health_label = Column(String(20), nullable=True)
    testing_score = Column(Integer, nullable=True)
    implementation_score = Column(Integer, nullable=True)
    evidence_freshness_score = Column(Integer, nullable=True)
    evidence_completeness_score = Column(Integer, nullable=True)
    findings_score = Column(Integer, nullable=True)
    snapshot_date = Column(DateTime, default=datetime.utcnow)

    implementation = relationship("ControlImplementation", backref="health_snapshots")


def backfill_controls_tables():
    """Migrate controls + control_tests tables: add new columns."""
    migrations = [
        ("control_tests", "status", "ALTER TABLE control_tests ADD COLUMN status VARCHAR(20) DEFAULT 'COMPLETED' NOT NULL"),
        ("control_tests", "scheduled_date", "ALTER TABLE control_tests ADD COLUMN scheduled_date DATETIME"),
        ("controls", "owner_user_id", "ALTER TABLE controls ADD COLUMN owner_user_id INTEGER"),
        ("controls", "objective", "ALTER TABLE controls ADD COLUMN objective TEXT"),
        ("controls", "procedure", "ALTER TABLE controls ADD COLUMN procedure TEXT"),
        ("controls", "operation_frequency", "ALTER TABLE controls ADD COLUMN operation_frequency VARCHAR(20)"),
        # Enhanced testing workpaper columns
        ("control_tests", "test_period_start", "ALTER TABLE control_tests ADD COLUMN test_period_start DATETIME"),
        ("control_tests", "test_period_end", "ALTER TABLE control_tests ADD COLUMN test_period_end DATETIME"),
        ("control_tests", "sample_size", "ALTER TABLE control_tests ADD COLUMN sample_size INTEGER"),
        ("control_tests", "population_size", "ALTER TABLE control_tests ADD COLUMN population_size INTEGER"),
        ("control_tests", "exceptions_count", "ALTER TABLE control_tests ADD COLUMN exceptions_count INTEGER DEFAULT 0"),
        ("control_tests", "exception_details", "ALTER TABLE control_tests ADD COLUMN exception_details TEXT"),
        ("control_tests", "conclusion", "ALTER TABLE control_tests ADD COLUMN conclusion TEXT"),
        ("control_tests", "finding_risk_rating", "ALTER TABLE control_tests ADD COLUMN finding_risk_rating VARCHAR(20)"),
        ("control_tests", "reviewer_user_id", "ALTER TABLE control_tests ADD COLUMN reviewer_user_id INTEGER"),
        ("control_tests", "review_date", "ALTER TABLE control_tests ADD COLUMN review_date DATETIME"),
        ("control_tests", "review_notes", "ALTER TABLE control_tests ADD COLUMN review_notes TEXT"),
        # Roll-forward testing columns
        ("control_tests", "is_roll_forward", "ALTER TABLE control_tests ADD COLUMN is_roll_forward BOOLEAN DEFAULT 0"),
        ("control_tests", "parent_test_id", "ALTER TABLE control_tests ADD COLUMN parent_test_id INTEGER"),
        # Control-level test/evidence instruction columns
        ("controls", "default_test_procedure", "ALTER TABLE controls ADD COLUMN default_test_procedure TEXT"),
        ("controls", "evidence_instructions", "ALTER TABLE controls ADD COLUMN evidence_instructions TEXT"),
        # Evidence as first-class entity columns
        ("control_evidence", "implementation_id", "ALTER TABLE control_evidence ADD COLUMN implementation_id INTEGER"),
        ("control_evidence", "framework_tags", "ALTER TABLE control_evidence ADD COLUMN framework_tags TEXT"),
    ]
    for table, col, sql in migrations:
        db = SessionLocal()
        try:
            existing = {r[1] for r in db.execute(text(f"PRAGMA table_info({table})")).fetchall()}
            if col not in existing:
                db.execute(text(sql))
                db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()

    # Rebuild control_evidence to make test_id nullable (Feature 7: evidence decoupled from tests)
    db = SessionLocal()
    try:
        cols = {r[1]: r[3] for r in db.execute(text("PRAGMA table_info(control_evidence)")).fetchall()}
        if cols.get("test_id") == 1:  # notnull == 1 means NOT NULL, need to fix
            db.execute(text("""
                CREATE TABLE IF NOT EXISTS control_evidence_new (
                    id INTEGER PRIMARY KEY,
                    test_id INTEGER,
                    original_filename VARCHAR(255) NOT NULL,
                    stored_filename VARCHAR(255) NOT NULL,
                    stored_path VARCHAR(512) NOT NULL,
                    content_type VARCHAR(100),
                    size_bytes INTEGER,
                    uploaded_at DATETIME,
                    implementation_id INTEGER,
                    framework_tags TEXT,
                    FOREIGN KEY(test_id) REFERENCES control_tests(id),
                    FOREIGN KEY(implementation_id) REFERENCES control_implementations(id)
                )
            """))
            db.execute(text("""
                INSERT INTO control_evidence_new
                SELECT id, test_id, original_filename, stored_filename, stored_path,
                       content_type, size_bytes, uploaded_at, implementation_id, framework_tags
                FROM control_evidence
            """))
            db.execute(text("DROP TABLE control_evidence"))
            db.execute(text("ALTER TABLE control_evidence_new RENAME TO control_evidence"))
            db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def seed_default_controls():
    """Seed 35 controls across 12 domains, each mapped to SOC 2 + ISO 27001 + NIST CSF 2.0."""
    db = SessionLocal()
    try:
        if db.query(Control).count() > 0:
            return

        seed_data = [
            # Access Control
            ("CTL-AC-001", "User Access Reviews", "Periodic review of user access rights to ensure appropriateness.",
             "Access Control", CONTROL_TYPE_DETECTIVE, CONTROL_IMPL_MANUAL, CONTROL_FREQ_QUARTERLY, "HIGH",
             [("SOC_2", "CC6.1"), ("ISO_27001", "A.9.2.5"), ("NIST_CSF_2", "PR.AC-1")]),
            ("CTL-AC-002", "Multi-Factor Authentication", "MFA enforced for all privileged and remote access.",
             "Access Control", CONTROL_TYPE_PREVENTIVE, CONTROL_IMPL_AUTOMATED, CONTROL_FREQ_CONTINUOUS, "CRITICAL",
             [("SOC_2", "CC6.1"), ("ISO_27001", "A.9.4.2"), ("NIST_CSF_2", "PR.AC-7")]),
            ("CTL-AC-003", "Least Privilege Enforcement", "Users granted minimum access necessary for their role.",
             "Access Control", CONTROL_TYPE_PREVENTIVE, CONTROL_IMPL_HYBRID, CONTROL_FREQ_QUARTERLY, "HIGH",
             [("SOC_2", "CC6.3"), ("ISO_27001", "A.9.1.2"), ("NIST_CSF_2", "PR.AC-4")]),

            # Cryptography
            ("CTL-CR-001", "Data Encryption at Rest", "All sensitive data encrypted at rest using AES-256 or equivalent.",
             "Cryptography", CONTROL_TYPE_PREVENTIVE, CONTROL_IMPL_AUTOMATED, CONTROL_FREQ_ANNUAL, "CRITICAL",
             [("SOC_2", "CC6.7"), ("ISO_27001", "A.10.1.1"), ("NIST_CSF_2", "PR.DS-1")]),
            ("CTL-CR-002", "Data Encryption in Transit", "All data in transit encrypted using TLS 1.2+.",
             "Cryptography", CONTROL_TYPE_PREVENTIVE, CONTROL_IMPL_AUTOMATED, CONTROL_FREQ_ANNUAL, "CRITICAL",
             [("SOC_2", "CC6.7"), ("ISO_27001", "A.10.1.1"), ("NIST_CSF_2", "PR.DS-2")]),
            ("CTL-CR-003", "Encryption Key Management", "Formal key management lifecycle including rotation and revocation.",
             "Cryptography", CONTROL_TYPE_PREVENTIVE, CONTROL_IMPL_HYBRID, CONTROL_FREQ_ANNUAL, "HIGH",
             [("SOC_2", "CC6.1"), ("ISO_27001", "A.10.1.2"), ("NIST_CSF_2", "PR.DS-1")]),

            # Incident Management
            ("CTL-IR-001", "Incident Response Plan", "Documented IRP with roles, escalation paths, and notification timelines.",
             "Incident Management", CONTROL_TYPE_CORRECTIVE, CONTROL_IMPL_MANUAL, CONTROL_FREQ_ANNUAL, "CRITICAL",
             [("SOC_2", "CC7.3"), ("ISO_27001", "A.16.1.1"), ("NIST_CSF_2", "RS.RP-1")]),
            ("CTL-IR-002", "Incident Detection & Alerting", "Automated detection and alerting for security incidents.",
             "Incident Management", CONTROL_TYPE_DETECTIVE, CONTROL_IMPL_AUTOMATED, CONTROL_FREQ_CONTINUOUS, "HIGH",
             [("SOC_2", "CC7.2"), ("ISO_27001", "A.16.1.2"), ("NIST_CSF_2", "DE.AE-5")]),
            ("CTL-IR-003", "Post-Incident Review", "Formal lessons-learned process after security incidents.",
             "Incident Management", CONTROL_TYPE_CORRECTIVE, CONTROL_IMPL_MANUAL, CONTROL_FREQ_ANNUAL, "MEDIUM",
             [("SOC_2", "CC7.5"), ("ISO_27001", "A.16.1.6"), ("NIST_CSF_2", "RS.IM-1")]),

            # Vulnerability Management
            ("CTL-VM-001", "Vulnerability Scanning", "Regular automated vulnerability scans of all production systems.",
             "Vulnerability Management", CONTROL_TYPE_DETECTIVE, CONTROL_IMPL_AUTOMATED, CONTROL_FREQ_MONTHLY, "HIGH",
             [("SOC_2", "CC7.1"), ("ISO_27001", "A.12.6.1"), ("NIST_CSF_2", "DE.CM-8")]),
            ("CTL-VM-002", "Penetration Testing", "Annual third-party penetration testing of critical systems.",
             "Vulnerability Management", CONTROL_TYPE_DETECTIVE, CONTROL_IMPL_MANUAL, CONTROL_FREQ_ANNUAL, "HIGH",
             [("SOC_2", "CC4.1"), ("ISO_27001", "A.18.2.3"), ("NIST_CSF_2", "DE.CM-8")]),
            ("CTL-VM-003", "Patch Management", "Timely patching of systems based on criticality and risk severity.",
             "Vulnerability Management", CONTROL_TYPE_CORRECTIVE, CONTROL_IMPL_HYBRID, CONTROL_FREQ_MONTHLY, "CRITICAL",
             [("SOC_2", "CC7.1"), ("ISO_27001", "A.12.6.1"), ("NIST_CSF_2", "PR.IP-12")]),

            # Business Continuity
            ("CTL-BC-001", "Business Continuity Plan", "Documented BCP covering critical business functions.",
             "Business Continuity", CONTROL_TYPE_CORRECTIVE, CONTROL_IMPL_MANUAL, CONTROL_FREQ_ANNUAL, "HIGH",
             [("SOC_2", "A1.2"), ("ISO_27001", "A.17.1.1"), ("NIST_CSF_2", "RC.RP-1")]),
            ("CTL-BC-002", "Disaster Recovery Testing", "Regular DR testing with documented results and RTO/RPO validation.",
             "Business Continuity", CONTROL_TYPE_DETECTIVE, CONTROL_IMPL_HYBRID, CONTROL_FREQ_ANNUAL, "HIGH",
             [("SOC_2", "A1.3"), ("ISO_27001", "A.17.1.3"), ("NIST_CSF_2", "RC.RP-1")]),
            ("CTL-BC-003", "Backup & Recovery", "Encrypted backups with geographic separation and regular restoration tests.",
             "Business Continuity", CONTROL_TYPE_PREVENTIVE, CONTROL_IMPL_AUTOMATED, CONTROL_FREQ_MONTHLY, "CRITICAL",
             [("SOC_2", "A1.2"), ("ISO_27001", "A.12.3.1"), ("NIST_CSF_2", "PR.IP-4")]),

            # Governance
            ("CTL-GV-001", "Security Policy Framework", "Documented and published security policies aligned to standards.",
             "Governance", CONTROL_TYPE_PREVENTIVE, CONTROL_IMPL_MANUAL, CONTROL_FREQ_ANNUAL, "HIGH",
             [("SOC_2", "CC1.1"), ("ISO_27001", "A.5.1.1"), ("NIST_CSF_2", "GV.PO-1")]),
            ("CTL-GV-002", "Risk Assessment Program", "Regular risk assessments aligned with recognized frameworks.",
             "Governance", CONTROL_TYPE_DETECTIVE, CONTROL_IMPL_MANUAL, CONTROL_FREQ_ANNUAL, "HIGH",
             [("SOC_2", "CC3.2"), ("ISO_27001", "A.8.2.1"), ("NIST_CSF_2", "ID.RA-1")]),
            ("CTL-GV-003", "Security Awareness Training", "Annual security awareness training for all personnel.",
             "Governance", CONTROL_TYPE_PREVENTIVE, CONTROL_IMPL_HYBRID, CONTROL_FREQ_ANNUAL, "MEDIUM",
             [("SOC_2", "CC1.4"), ("ISO_27001", "A.7.2.2"), ("NIST_CSF_2", "PR.AT-1")]),

            # Data Protection
            ("CTL-DP-001", "Data Classification", "Formal data classification scheme with handling requirements.",
             "Data Protection", CONTROL_TYPE_PREVENTIVE, CONTROL_IMPL_MANUAL, CONTROL_FREQ_ANNUAL, "HIGH",
             [("SOC_2", "CC6.5"), ("ISO_27001", "A.8.2.1"), ("NIST_CSF_2", "ID.AM-5")]),
            ("CTL-DP-002", "Data Loss Prevention", "DLP controls to prevent unauthorized data exfiltration.",
             "Data Protection", CONTROL_TYPE_PREVENTIVE, CONTROL_IMPL_AUTOMATED, CONTROL_FREQ_CONTINUOUS, "HIGH",
             [("SOC_2", "CC6.7"), ("ISO_27001", "A.13.2.1"), ("NIST_CSF_2", "PR.DS-5")]),
            ("CTL-DP-003", "Data Retention & Disposal", "Formal data retention schedule and secure disposal procedures.",
             "Data Protection", CONTROL_TYPE_PREVENTIVE, CONTROL_IMPL_HYBRID, CONTROL_FREQ_ANNUAL, "MEDIUM",
             [("SOC_2", "CC6.5"), ("ISO_27001", "A.8.3.2"), ("NIST_CSF_2", "PR.IP-6")]),

            # Security Monitoring
            ("CTL-SM-001", "SIEM / Log Aggregation", "Centralized security event logging and correlation.",
             "Security Monitoring", CONTROL_TYPE_DETECTIVE, CONTROL_IMPL_AUTOMATED, CONTROL_FREQ_CONTINUOUS, "HIGH",
             [("SOC_2", "CC7.2"), ("ISO_27001", "A.12.4.1"), ("NIST_CSF_2", "DE.AE-3")]),
            ("CTL-SM-002", "Audit Log Integrity", "Tamper-evident audit logs with restricted access.",
             "Security Monitoring", CONTROL_TYPE_DETECTIVE, CONTROL_IMPL_AUTOMATED, CONTROL_FREQ_CONTINUOUS, "HIGH",
             [("SOC_2", "CC7.2"), ("ISO_27001", "A.12.4.2"), ("NIST_CSF_2", "PR.PT-1")]),

            # Network Security
            ("CTL-NS-001", "Network Segmentation", "Production networks segmented from corporate and development.",
             "Network Security", CONTROL_TYPE_PREVENTIVE, CONTROL_IMPL_AUTOMATED, CONTROL_FREQ_ANNUAL, "HIGH",
             [("SOC_2", "CC6.6"), ("ISO_27001", "A.13.1.3"), ("NIST_CSF_2", "PR.AC-5")]),
            ("CTL-NS-002", "Firewall Management", "Firewall rules reviewed and documented with change control.",
             "Network Security", CONTROL_TYPE_PREVENTIVE, CONTROL_IMPL_HYBRID, CONTROL_FREQ_QUARTERLY, "HIGH",
             [("SOC_2", "CC6.6"), ("ISO_27001", "A.13.1.1"), ("NIST_CSF_2", "PR.PT-4")]),

            # Change Management
            ("CTL-CM-001", "Change Management Process", "Formal change control process for production environments.",
             "Change Management", CONTROL_TYPE_PREVENTIVE, CONTROL_IMPL_HYBRID, CONTROL_FREQ_CONTINUOUS, "HIGH",
             [("SOC_2", "CC8.1"), ("ISO_27001", "A.12.1.2"), ("NIST_CSF_2", "PR.IP-3")]),
            ("CTL-CM-002", "Configuration Baseline", "Documented configuration baselines for critical systems.",
             "Change Management", CONTROL_TYPE_PREVENTIVE, CONTROL_IMPL_HYBRID, CONTROL_FREQ_QUARTERLY, "MEDIUM",
             [("SOC_2", "CC8.1"), ("ISO_27001", "A.12.1.1"), ("NIST_CSF_2", "PR.IP-1")]),

            # Third-Party Management
            ("CTL-TP-001", "Third-Party Risk Assessment", "Formal vendor risk assessment for all third-party providers.",
             "Third-Party Management", CONTROL_TYPE_DETECTIVE, CONTROL_IMPL_MANUAL, CONTROL_FREQ_ANNUAL, "HIGH",
             [("SOC_2", "CC9.2"), ("ISO_27001", "A.15.1.1"), ("NIST_CSF_2", "ID.SC-1")]),
            ("CTL-TP-002", "Vendor Contract Security Requirements", "Security requirements embedded in vendor contracts.",
             "Third-Party Management", CONTROL_TYPE_PREVENTIVE, CONTROL_IMPL_MANUAL, CONTROL_FREQ_ANNUAL, "MEDIUM",
             [("SOC_2", "CC9.2"), ("ISO_27001", "A.15.1.2"), ("NIST_CSF_2", "ID.SC-3")]),

            # Physical Security
            ("CTL-PS-001", "Physical Access Controls", "Badge access and visitor management for secure areas.",
             "Physical Security", CONTROL_TYPE_PREVENTIVE, CONTROL_IMPL_HYBRID, CONTROL_FREQ_QUARTERLY, "MEDIUM",
             [("SOC_2", "CC6.4"), ("ISO_27001", "A.11.1.2"), ("NIST_CSF_2", "PR.AC-2")]),
            ("CTL-PS-002", "Environmental Controls", "Fire suppression, HVAC, and power redundancy for data centers.",
             "Physical Security", CONTROL_TYPE_PREVENTIVE, CONTROL_IMPL_AUTOMATED, CONTROL_FREQ_ANNUAL, "MEDIUM",
             [("SOC_2", "A1.1"), ("ISO_27001", "A.11.1.4"), ("NIST_CSF_2", "PR.IP-5")]),

            # Secure Development
            ("CTL-SD-001", "Secure SDLC", "Security integrated into all phases of the development lifecycle.",
             "Secure Development", CONTROL_TYPE_PREVENTIVE, CONTROL_IMPL_HYBRID, CONTROL_FREQ_CONTINUOUS, "HIGH",
             [("SOC_2", "CC8.1"), ("ISO_27001", "A.14.2.1"), ("NIST_CSF_2", "PR.IP-2")]),
            ("CTL-SD-002", "Code Review & Static Analysis", "Mandatory code reviews and SAST before production deployment.",
             "Secure Development", CONTROL_TYPE_DETECTIVE, CONTROL_IMPL_AUTOMATED, CONTROL_FREQ_CONTINUOUS, "HIGH",
             [("SOC_2", "CC8.1"), ("ISO_27001", "A.14.2.5"), ("NIST_CSF_2", "PR.IP-2")]),

            # Asset Management
            ("CTL-AM-001", "Asset Inventory", "Comprehensive hardware and software asset inventory maintained.",
             "Asset Management", CONTROL_TYPE_DETECTIVE, CONTROL_IMPL_HYBRID, CONTROL_FREQ_QUARTERLY, "MEDIUM",
             [("SOC_2", "CC6.1"), ("ISO_27001", "A.8.1.1"), ("NIST_CSF_2", "ID.AM-1")]),
            ("CTL-AM-002", "Endpoint Protection", "Antivirus/EDR deployed on all endpoints with central management.",
             "Asset Management", CONTROL_TYPE_PREVENTIVE, CONTROL_IMPL_AUTOMATED, CONTROL_FREQ_CONTINUOUS, "HIGH",
             [("SOC_2", "CC6.8"), ("ISO_27001", "A.12.2.1"), ("NIST_CSF_2", "DE.CM-4")]),
        ]

        for ref, title, desc, domain, ctype, itype, freq, crit, mappings in seed_data:
            ctrl = Control(
                control_ref=ref, title=title, description=desc,
                domain=domain, control_type=ctype, implementation_type=itype,
                test_frequency=freq, criticality=crit, is_active=True,
            )
            db.add(ctrl)
            db.flush()
            for fw, reference in mappings:
                db.add(ControlFrameworkMapping(
                    control_id=ctrl.id, framework=fw, reference=reference,
                ))

        db.commit()
    finally:
        db.close()


def update_control_enrichments():
    """Backfill objective, procedure, default_test_procedure on existing controls.
    Also updates framework mapping references from 2013/1.1 numbering to 2022/2.0."""
    db = SessionLocal()
    try:
        # Enrichment data keyed by control_ref
        enrichments = {
            "CTL-AC-001": {
                "objective": "Ensure user access rights remain appropriate and aligned with job responsibilities.",
                "procedure": "Review all user accounts quarterly; validate access levels with managers; remove stale accounts.",
                "default_test_procedure": "Select sample of users; confirm access matches current role; verify terminated users removed.",
            },
            "CTL-AC-002": {
                "objective": "Prevent unauthorized access through strong multi-factor authentication.",
                "procedure": "Enforce MFA for all privileged and remote access; monitor MFA enrollment compliance.",
                "default_test_procedure": "Attempt login without MFA; verify enforcement on privileged accounts; check enrollment rates.",
            },
            "CTL-AC-003": {
                "objective": "Limit access to the minimum necessary for each role.",
                "procedure": "Define role-based access profiles; review and adjust permissions quarterly.",
                "default_test_procedure": "Compare user permissions to role definitions; identify over-provisioned accounts.",
            },
            "CTL-CR-001": {
                "objective": "Protect sensitive data at rest from unauthorized disclosure.",
                "procedure": "Encrypt all databases and storage volumes using AES-256; verify encryption status monthly.",
                "default_test_procedure": "Verify encryption enabled on all production databases and storage; check key strength.",
            },
            "CTL-CR-002": {
                "objective": "Protect data in transit from interception or tampering.",
                "procedure": "Enforce TLS 1.2+ on all endpoints; disable weak cipher suites; scan for plaintext transmissions.",
                "default_test_procedure": "Scan endpoints for TLS configuration; verify no plaintext data channels exist.",
            },
            "CTL-CR-003": {
                "objective": "Ensure cryptographic keys are managed securely throughout their lifecycle.",
                "procedure": "Use HSM or KMS for key storage; rotate keys per schedule; revoke compromised keys immediately.",
                "default_test_procedure": "Review key rotation logs; verify key storage in HSM/KMS; check revocation procedures.",
            },
            "CTL-IR-001": {
                "objective": "Ensure the organization can respond effectively to security incidents.",
                "procedure": "Maintain documented IRP; conduct tabletop exercises annually; update after incidents.",
                "default_test_procedure": "Review IRP document currency; verify annual tabletop exercise; check post-incident updates.",
            },
            "CTL-IR-002": {
                "objective": "Detect security incidents promptly through automated monitoring.",
                "procedure": "Configure SIEM alerts for critical events; tune detection rules; review alert volume weekly.",
                "default_test_procedure": "Inject test events; verify alerts fire within SLA; review false positive rates.",
            },
            "CTL-IR-003": {
                "objective": "Learn from incidents to prevent recurrence.",
                "procedure": "Conduct post-incident review within 5 business days; document lessons learned; track remediation actions.",
                "default_test_procedure": "Review post-incident reports; verify action items completed; check trend analysis.",
            },
            "CTL-VM-001": {
                "objective": "Identify vulnerabilities in production systems before exploitation.",
                "procedure": "Run authenticated vulnerability scans monthly; prioritize by CVSS score; track remediation.",
                "default_test_procedure": "Review scan coverage and frequency; verify critical findings remediated within SLA.",
            },
            "CTL-VM-002": {
                "objective": "Validate security controls through independent adversarial testing.",
                "procedure": "Engage third-party penetration testers annually; scope all critical systems; remediate findings.",
                "default_test_procedure": "Review pentest report; verify scope coverage; confirm critical findings remediated.",
            },
            "CTL-VM-003": {
                "objective": "Maintain systems at current patch levels to reduce attack surface.",
                "procedure": "Apply critical patches within 72 hours; high within 30 days; standard within 90 days.",
                "default_test_procedure": "Sample systems for patch currency; verify patching SLAs met; check exception approvals.",
            },
            "CTL-BC-001": {
                "objective": "Ensure critical business functions can continue during disruption.",
                "procedure": "Maintain BCP covering all critical functions; review annually; update after organizational changes.",
                "default_test_procedure": "Review BCP document; verify coverage of critical functions; check review dates.",
            },
            "CTL-BC-002": {
                "objective": "Validate disaster recovery capabilities meet RTO/RPO targets.",
                "procedure": "Conduct DR test annually; measure actual RTO/RPO; document results and gaps.",
                "default_test_procedure": "Review DR test results; compare actual vs target RTO/RPO; verify gap remediation.",
            },
            "CTL-BC-003": {
                "objective": "Ensure data can be recovered from backups when needed.",
                "procedure": "Perform encrypted backups with geographic separation; test restoration monthly.",
                "default_test_procedure": "Verify backup completion logs; perform test restoration; check geographic separation.",
            },
            "CTL-GV-001": {
                "objective": "Establish security governance through documented policies.",
                "procedure": "Publish security policies; obtain management approval; communicate to all personnel annually.",
                "default_test_procedure": "Review policy documents; verify management approval signatures; check acknowledgment records.",
            },
            "CTL-GV-002": {
                "objective": "Understand organizational risk through formal assessment.",
                "procedure": "Conduct risk assessment annually; align with recognized framework; report to management.",
                "default_test_procedure": "Review risk assessment report; verify methodology alignment; check management review.",
            },
            "CTL-GV-003": {
                "objective": "Build security awareness across the organization.",
                "procedure": "Deliver annual security awareness training; track completion; conduct phishing simulations.",
                "default_test_procedure": "Review training completion rates; verify content currency; check phishing simulation results.",
            },
            "CTL-DP-001": {
                "objective": "Classify data appropriately to apply correct handling controls.",
                "procedure": "Maintain data classification scheme; label all data repositories; review classifications annually.",
                "default_test_procedure": "Review classification scheme; sample repositories for correct labeling; verify handling procedures.",
            },
            "CTL-DP-002": {
                "objective": "Prevent unauthorized data exfiltration.",
                "procedure": "Deploy DLP on endpoints and network egress; configure policies for sensitive data patterns; review alerts.",
                "default_test_procedure": "Test DLP detection with sample sensitive data; review alert logs; verify policy coverage.",
            },
            "CTL-DP-003": {
                "objective": "Ensure data is retained appropriately and disposed of securely.",
                "procedure": "Maintain retention schedule; automate retention enforcement; use secure disposal for expired data.",
                "default_test_procedure": "Review retention schedule; verify automated enforcement; check secure disposal certificates.",
            },
            "CTL-SM-001": {
                "objective": "Provide centralized security event visibility and correlation.",
                "procedure": "Aggregate logs from all critical systems; configure correlation rules; review dashboards daily.",
                "default_test_procedure": "Verify log source coverage; test correlation rules; review analyst response times.",
            },
            "CTL-SM-002": {
                "objective": "Ensure audit logs cannot be tampered with.",
                "procedure": "Write logs to immutable storage; restrict access to log infrastructure; monitor for gaps.",
                "default_test_procedure": "Verify immutable storage configuration; test access restrictions; check for log gaps.",
            },
            "CTL-NS-001": {
                "objective": "Reduce lateral movement risk through network segmentation.",
                "procedure": "Segment production from corporate and development; maintain network diagrams; review annually.",
                "default_test_procedure": "Review network diagrams; test segmentation boundaries; verify firewall rules enforce separation.",
            },
            "CTL-NS-002": {
                "objective": "Maintain secure and documented firewall configurations.",
                "procedure": "Review firewall rules quarterly; remove unused rules; document change justifications.",
                "default_test_procedure": "Review firewall rule sets; verify quarterly review evidence; check for overly permissive rules.",
            },
            "CTL-CM-001": {
                "objective": "Prevent unauthorized changes to production environments.",
                "procedure": "Require change requests with approval; test in staging; maintain rollback plans.",
                "default_test_procedure": "Review change records; verify approval workflow; check for unauthorized changes.",
            },
            "CTL-CM-002": {
                "objective": "Maintain known-good configuration baselines.",
                "procedure": "Document baselines for critical systems; scan for drift quarterly; remediate deviations.",
                "default_test_procedure": "Review baseline documents; verify drift scanning; check deviation remediation.",
            },
            "CTL-TP-001": {
                "objective": "Assess risk from third-party service providers.",
                "procedure": "Conduct risk assessments for all vendors; tier by criticality; reassess per schedule.",
                "default_test_procedure": "Review vendor risk assessments; verify tiering methodology; check reassessment compliance.",
            },
            "CTL-TP-002": {
                "objective": "Embed security requirements in vendor contracts.",
                "procedure": "Include security clauses in all vendor contracts; review during renewals.",
                "default_test_procedure": "Review sample vendor contracts; verify security clauses present; check renewal reviews.",
            },
            "CTL-PS-001": {
                "objective": "Control physical access to secure areas.",
                "procedure": "Implement badge access for secure areas; manage visitor logs; review access lists quarterly.",
                "default_test_procedure": "Review badge access logs; verify visitor management; check quarterly access reviews.",
            },
            "CTL-PS-002": {
                "objective": "Protect facilities from environmental threats.",
                "procedure": "Maintain fire suppression, HVAC, and UPS systems; test annually; document maintenance.",
                "default_test_procedure": "Review maintenance records; verify annual testing; check alarm functionality.",
            },
            "CTL-SD-001": {
                "objective": "Integrate security into the software development lifecycle.",
                "procedure": "Require security reviews at each SDLC phase; maintain secure coding standards; track security defects.",
                "default_test_procedure": "Review SDLC documentation; verify security gate compliance; check defect tracking.",
            },
            "CTL-SD-002": {
                "objective": "Identify security defects before production deployment.",
                "procedure": "Require code reviews and SAST scans for all changes; block deployment on critical findings.",
                "default_test_procedure": "Review code review records; verify SAST scan coverage; check deployment gate enforcement.",
            },
            "CTL-AM-001": {
                "objective": "Maintain comprehensive awareness of all IT assets.",
                "procedure": "Maintain hardware and software inventory; reconcile quarterly; tag all assets.",
                "default_test_procedure": "Review asset inventory; verify quarterly reconciliation; sample physical assets against records.",
            },
            "CTL-AM-002": {
                "objective": "Protect endpoints from malware and unauthorized access.",
                "procedure": "Deploy EDR/antivirus on all endpoints; ensure central management; review detections weekly.",
                "default_test_procedure": "Verify endpoint coverage rates; review detection logs; test with EICAR samples.",
            },
        }

        # Updated framework reference mappings (old → new)
        ref_updates = {
            # ISO 27001: 2013 → 2022 numbering
            ("ISO_27001", "A.9.2.5"): "A.5.18",   # Access rights
            ("ISO_27001", "A.9.4.2"): "A.8.5",    # Secure authentication
            ("ISO_27001", "A.9.1.2"): "A.5.15",   # Access control policy
            ("ISO_27001", "A.10.1.1"): "A.8.24",  # Use of cryptography
            ("ISO_27001", "A.10.1.2"): "A.8.24",  # Key management
            ("ISO_27001", "A.16.1.1"): "A.5.24",  # Incident management planning
            ("ISO_27001", "A.16.1.2"): "A.6.8",   # Reporting security events
            ("ISO_27001", "A.16.1.6"): "A.5.27",  # Learning from incidents
            ("ISO_27001", "A.12.6.1"): "A.8.8",   # Management of technical vulnerabilities
            ("ISO_27001", "A.18.2.3"): "A.5.35",  # Independent review
            ("ISO_27001", "A.17.1.1"): "A.5.29",  # Info security during disruption
            ("ISO_27001", "A.17.1.3"): "A.5.30",  # ICT readiness for BC
            ("ISO_27001", "A.12.3.1"): "A.8.13",  # Information backup
            ("ISO_27001", "A.5.1.1"): "A.5.1",    # Policies for info security
            ("ISO_27001", "A.8.2.1"): "A.5.12",   # Classification of information
            ("ISO_27001", "A.7.2.2"): "A.6.3",    # Security awareness training
            ("ISO_27001", "A.13.2.1"): "A.5.14",  # Information transfer
            ("ISO_27001", "A.8.3.2"): "A.7.10",   # Storage media
            ("ISO_27001", "A.12.4.1"): "A.8.15",  # Logging
            ("ISO_27001", "A.12.4.2"): "A.8.15",  # Logging (protection)
            ("ISO_27001", "A.13.1.3"): "A.8.22",  # Segregation of networks
            ("ISO_27001", "A.13.1.1"): "A.8.20",  # Network security
            ("ISO_27001", "A.12.1.2"): "A.8.32",  # Change management
            ("ISO_27001", "A.12.1.1"): "A.8.9",   # Configuration management
            ("ISO_27001", "A.15.1.1"): "A.5.19",  # Supplier relationships
            ("ISO_27001", "A.15.1.2"): "A.5.20",  # Supplier agreements
            ("ISO_27001", "A.11.1.2"): "A.7.2",   # Physical entry
            ("ISO_27001", "A.11.1.4"): "A.7.5",   # Protecting against threats
            ("ISO_27001", "A.14.2.1"): "A.8.25",  # Secure development lifecycle
            ("ISO_27001", "A.14.2.5"): "A.8.29",  # Security testing
            ("ISO_27001", "A.8.1.1"): "A.5.9",    # Inventory of assets
            ("ISO_27001", "A.12.2.1"): "A.8.7",   # Protection against malware
            # NIST CSF: 1.1 → 2.0 numbering
            ("NIST_CSF_2", "PR.AC-1"): "PR.AA-01",
            ("NIST_CSF_2", "PR.AC-7"): "PR.AA-03",
            ("NIST_CSF_2", "PR.AC-4"): "PR.AA-05",
            ("NIST_CSF_2", "PR.DS-1"): "PR.DS-01",
            ("NIST_CSF_2", "PR.DS-2"): "PR.DS-02",
            ("NIST_CSF_2", "PR.DS-5"): "PR.DS-10",
            ("NIST_CSF_2", "RS.RP-1"): "RS.MA-01",
            ("NIST_CSF_2", "DE.AE-5"): "DE.AE-07",
            ("NIST_CSF_2", "RS.IM-1"): "RS.MA-05",
            ("NIST_CSF_2", "DE.CM-8"): "DE.CM-09",
            ("NIST_CSF_2", "DE.CM-4"): "DE.CM-01",
            ("NIST_CSF_2", "PR.IP-12"): "PR.PS-02",
            ("NIST_CSF_2", "RC.RP-1"): "RC.RP-01",
            ("NIST_CSF_2", "GV.PO-1"): "GV.PO-01",
            ("NIST_CSF_2", "ID.RA-1"): "ID.RA-01",
            ("NIST_CSF_2", "PR.AT-1"): "PR.AT-01",
            ("NIST_CSF_2", "ID.AM-5"): "ID.AM-05",
            ("NIST_CSF_2", "PR.IP-6"): "PR.DS-11",
            ("NIST_CSF_2", "DE.AE-3"): "DE.AE-03",
            ("NIST_CSF_2", "PR.PT-1"): "PR.PS-01",
            ("NIST_CSF_2", "PR.AC-5"): "PR.AA-06",
            ("NIST_CSF_2", "PR.PT-4"): "PR.IR-01",
            ("NIST_CSF_2", "PR.IP-3"): "PR.PS-04",
            ("NIST_CSF_2", "PR.IP-1"): "PR.PS-01",
            ("NIST_CSF_2", "ID.SC-1"): "GV.SC-01",
            ("NIST_CSF_2", "ID.SC-3"): "GV.SC-05",
            ("NIST_CSF_2", "PR.AC-2"): "PR.AA-02",
            ("NIST_CSF_2", "PR.IP-5"): "PR.PS-05",
            ("NIST_CSF_2", "PR.IP-2"): "PR.PS-06",
            ("NIST_CSF_2", "PR.IP-4"): "PR.DS-11",
            ("NIST_CSF_2", "ID.AM-1"): "ID.AM-01",
        }

        for ctrl in db.query(Control).all():
            enrich = enrichments.get(ctrl.control_ref)
            if enrich:
                if not ctrl.objective:
                    ctrl.objective = enrich.get("objective")
                if not ctrl.procedure:
                    ctrl.procedure = enrich.get("procedure")
                if not ctrl.default_test_procedure:
                    ctrl.default_test_procedure = enrich.get("default_test_procedure")

        # Update framework mapping references
        for mapping in db.query(ControlFrameworkMapping).all():
            key = (mapping.framework, mapping.reference)
            if key in ref_updates:
                mapping.reference = ref_updates[key]

        db.commit()
    finally:
        db.close()


# ==================== FRAMEWORK REQUIREMENT LIBRARY ====================

ADOPTION_STATUS_NOT_ADDRESSED = "NOT_ADDRESSED"
ADOPTION_STATUS_MAPPED = "MAPPED"
ADOPTION_STATUS_NOT_APPLICABLE = "NOT_APPLICABLE"
VALID_ADOPTION_STATUSES = [ADOPTION_STATUS_NOT_ADDRESSED, ADOPTION_STATUS_MAPPED, ADOPTION_STATUS_NOT_APPLICABLE]
ADOPTION_STATUS_LABELS = {
    ADOPTION_STATUS_NOT_ADDRESSED: "Not Addressed",
    ADOPTION_STATUS_MAPPED: "Mapped",
    ADOPTION_STATUS_NOT_APPLICABLE: "N/A",
}
ADOPTION_STATUS_COLORS = {
    ADOPTION_STATUS_NOT_ADDRESSED: "#dc3545",
    ADOPTION_STATUS_MAPPED: "#198754",
    ADOPTION_STATUS_NOT_APPLICABLE: "#6c757d",
}

# Frameworks with seeded canonical requirements
SEEDED_FRAMEWORKS = ["SOC_2", "ISO_27001", "NIST_CSF_2", "CMMC_2"]


class FrameworkRequirement(Base):
    """Canonical requirement from a regulatory/compliance framework."""
    __tablename__ = "framework_requirements"

    id = Column(Integer, primary_key=True, index=True)
    framework = Column(String(50), nullable=False, index=True)
    reference = Column(String(100), nullable=False, index=True)
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    guidance = Column(Text, nullable=True)
    category = Column(String(200), nullable=True, index=True)
    subcategory = Column(String(200), nullable=True)
    suggested_domain = Column(String(100), nullable=True)
    suggested_control_type = Column(String(20), nullable=True)
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        # Unique constraint on (framework, reference)
        {"sqlite_autoincrement": True},
    )


class FrameworkAdoption(Base):
    """Organization's adoption decision for each framework requirement."""
    __tablename__ = "framework_adoptions"

    id = Column(Integer, primary_key=True, index=True)
    framework = Column(String(50), nullable=False, index=True)
    requirement_reference = Column(String(100), nullable=False, index=True)
    status = Column(String(30), default=ADOPTION_STATUS_NOT_ADDRESSED, nullable=False)
    control_id = Column(Integer, ForeignKey("controls.id"), nullable=True)
    notes = Column(Text, nullable=True)
    adopted_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    adopted_at = Column(DateTime, nullable=True)

    control = relationship("Control")
    adopted_by = relationship("User", foreign_keys=[adopted_by_user_id])

    __table_args__ = (
        {"sqlite_autoincrement": True},
    )


def backfill_framework_tables():
    """Create framework_requirements and framework_adoptions tables if missing."""
    db = SessionLocal()
    try:
        existing_tables = {r[0] for r in db.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()}
        if "framework_requirements" not in existing_tables:
            FrameworkRequirement.__table__.create(engine, checkfirst=True)
        if "framework_adoptions" not in existing_tables:
            FrameworkAdoption.__table__.create(engine, checkfirst=True)
    finally:
        db.close()


def seed_framework_requirements():
    """Load canonical framework requirements from seed data, seeding any missing frameworks."""
    db = SessionLocal()
    try:
        from app.services.framework_seeds import get_all_framework_seeds
        seeds = get_all_framework_seeds()

        # Find which frameworks already have seeds in DB
        existing_frameworks = set(
            r[0] for r in db.query(FrameworkRequirement.framework).distinct().all()
        )

        new_seeds = [s for s in seeds if s["framework"] not in existing_frameworks]
        if not new_seeds:
            return

        for s in new_seeds:
            db.add(FrameworkRequirement(
                framework=s["framework"],
                reference=s["reference"],
                title=s["title"],
                description=s.get("description", ""),
                guidance=s.get("guidance"),
                category=s.get("category"),
                subcategory=s.get("subcategory"),
                suggested_domain=s.get("suggested_domain"),
                suggested_control_type=s.get("suggested_control_type"),
                sort_order=s.get("sort_order", 0),
            ))
        db.commit()
    finally:
        db.close()


def sync_adoptions_from_existing_mappings():
    """Create FrameworkAdoption records for existing ControlFrameworkMapping rows
    that match seeded requirements (one-time sync for existing databases)."""
    db = SessionLocal()
    try:
        # Only sync if we have requirements but no adoptions yet
        if db.query(FrameworkAdoption).count() > 0:
            return
        if db.query(FrameworkRequirement).count() == 0:
            return

        # Build lookup of seeded requirements
        reqs = db.query(FrameworkRequirement).all()
        req_set = {(r.framework, r.reference) for r in reqs}

        # Find existing mappings that match
        mappings = db.query(ControlFrameworkMapping).all()
        for m in mappings:
            if (m.framework, m.reference) in req_set:
                db.add(FrameworkAdoption(
                    framework=m.framework,
                    requirement_reference=m.reference,
                    status=ADOPTION_STATUS_MAPPED,
                    control_id=m.control_id,
                    adopted_at=datetime.utcnow(),
                ))
        db.commit()
    finally:
        db.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
