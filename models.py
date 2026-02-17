from sqlalchemy import create_engine, Column, Integer, String, Text, ForeignKey, DateTime, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime

DATABASE_URL = "sqlite:///./questionnaires.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class QuestionBankItem(Base):
    __tablename__ = "question_bank_items"

    id = Column(Integer, primary_key=True, index=True)
    category = Column(String(100), nullable=False, index=True)
    text = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


VENDOR_STATUS_ACTIVE = "ACTIVE"
VENDOR_STATUS_ARCHIVED = "ARCHIVED"
VALID_VENDOR_STATUSES = [VENDOR_STATUS_ACTIVE, VENDOR_STATUS_ARCHIVED]


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

    assessments = relationship("Assessment", back_populates="vendor")


# ==================== ASSESSMENT TEMPLATE ====================

class AssessmentTemplate(Base):
    __tablename__ = "assessment_templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    source_title = Column(String(255), nullable=True)
    source_company = Column(String(255), nullable=True)
    token = Column(String(64), unique=True, nullable=False, index=True)
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
    submitted_at = Column(DateTime, nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    vendor = relationship("Vendor", back_populates="assessments")
    template = relationship("AssessmentTemplate")
    questions = relationship("Question", back_populates="assessment", cascade="all, delete-orphan")
    responses = relationship("Response", back_populates="assessment", cascade="all, delete-orphan")
    conditional_rules = relationship("ConditionalRule", back_populates="assessment", cascade="all, delete-orphan")


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
    answer_choice = Column(String(20), nullable=True)
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
DECISION_STATUS_FINAL = "FINAL"
VALID_DECISION_STATUSES = [DECISION_STATUS_DRAFT, DECISION_STATUS_FINAL]

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
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    finalized_at = Column(DateTime, nullable=True)

    vendor = relationship("Vendor")
    assessment = relationship("Assessment")


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
    trigger_answer_value = Column(String(20), nullable=True)

    trigger_question = relationship("QuestionBankItem")


VALID_CHOICES = ["yes", "no", "partial", "na"]

EVAL_MEETS = "MEETS_EXPECTATION"
EVAL_PARTIAL = "PARTIALLY_MEETS_EXPECTATION"
EVAL_DOES_NOT_MEET = "DOES_NOT_MEET_EXPECTATION"
EVAL_NO_EXPECTATION = "NO_EXPECTATION_DEFINED"


def compute_expectation_status(expected_value, answer_choice, expected_values=None, answer_mode="SINGLE"):
    """
    Compute evaluation status by comparing vendor answer to expected answer(s).
    Returns one of: EVAL_MEETS, EVAL_PARTIAL, EVAL_DOES_NOT_MEET, EVAL_NO_EXPECTATION
    """
    import json

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
        elif intersection:
            return EVAL_PARTIAL
        else:
            return EVAL_DOES_NOT_MEET
    else:
        answer_lower = answer_choice.lower()

        if answer_lower in expected_set:
            return EVAL_MEETS

        if answer_lower == "partial" and "yes" in expected_set:
            return EVAL_PARTIAL

        return EVAL_DOES_NOT_MEET


def init_db():
    Base.metadata.create_all(bind=engine)


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


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
