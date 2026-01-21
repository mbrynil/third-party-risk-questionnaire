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

    questionnaires = relationship("Questionnaire", back_populates="vendor")


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


class Questionnaire(Base):
    __tablename__ = "questionnaires"

    id = Column(Integer, primary_key=True, index=True)
    company_name = Column(String(255), nullable=False)
    title = Column(String(255), nullable=False)
    token = Column(String(64), unique=True, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_template = Column(Boolean, default=False, nullable=False)
    template_name = Column(String(255), nullable=True)
    template_description = Column(Text, nullable=True)
    vendor_id = Column(Integer, ForeignKey("vendors.id"), nullable=True)
    status = Column(String(20), default=ASSESSMENT_STATUS_DRAFT, nullable=False)
    sent_at = Column(DateTime, nullable=True)
    submitted_at = Column(DateTime, nullable=True)
    reviewed_at = Column(DateTime, nullable=True)

    vendor = relationship("Vendor", back_populates="questionnaires")
    questions = relationship("Question", back_populates="questionnaire", cascade="all, delete-orphan")
    responses = relationship("Response", back_populates="questionnaire", cascade="all, delete-orphan")
    conditional_rules = relationship("ConditionalRule", back_populates="questionnaire", cascade="all, delete-orphan")


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
    questionnaire_id = Column(Integer, ForeignKey("questionnaires.id"), nullable=False)
    question_text = Column(Text, nullable=False)
    order = Column(Integer, default=0)
    weight = Column(String(20), default=WEIGHT_MEDIUM, nullable=False)
    expected_operator = Column(String(20), default=OPERATOR_EQUALS, nullable=False)
    expected_value = Column(String(50), nullable=True)
    expected_values = Column(Text, nullable=True)  # JSON array of acceptable answers e.g. '["yes","partial"]'
    expected_value_type = Column(String(20), default=VALUE_TYPE_CHOICE, nullable=False)
    answer_mode = Column(String(20), default=ANSWER_MODE_SINGLE, nullable=False)

    questionnaire = relationship("Questionnaire", back_populates="questions")


RESPONSE_STATUS_DRAFT = "DRAFT"
RESPONSE_STATUS_SUBMITTED = "SUBMITTED"
RESPONSE_STATUS_NEEDS_INFO = "NEEDS_INFO"


class Response(Base):
    __tablename__ = "responses"

    id = Column(Integer, primary_key=True, index=True)
    questionnaire_id = Column(Integer, ForeignKey("questionnaires.id"), nullable=False)
    vendor_name = Column(String(255), nullable=False)
    vendor_email = Column(String(255), nullable=False)
    status = Column(String(20), default=RESPONSE_STATUS_DRAFT, nullable=False)
    submitted_at = Column(DateTime, default=datetime.utcnow)
    last_saved_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    questionnaire = relationship("Questionnaire", back_populates="responses")
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
    questionnaire_id = Column(Integer, ForeignKey("questionnaires.id"), nullable=False)
    response_id = Column(Integer, ForeignKey("responses.id"), nullable=False)
    original_filename = Column(String(255), nullable=False)
    stored_filename = Column(String(255), nullable=False)
    stored_path = Column(String(512), nullable=False)
    content_type = Column(String(100), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    uploaded_at = Column(DateTime, default=datetime.utcnow)

    questionnaire = relationship("Questionnaire")
    response = relationship("Response", back_populates="evidence_files")


class FollowUp(Base):
    __tablename__ = "follow_ups"

    id = Column(Integer, primary_key=True, index=True)
    response_id = Column(Integer, ForeignKey("responses.id"), nullable=False)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    response_text = Column(Text, nullable=True)
    responded_at = Column(DateTime, nullable=True)

    response = relationship("Response", back_populates="follow_ups")


class ConditionalRule(Base):
    __tablename__ = "conditional_rules"

    id = Column(Integer, primary_key=True, index=True)
    questionnaire_id = Column(Integer, ForeignKey("questionnaires.id"), nullable=False)
    trigger_question_id = Column(Integer, ForeignKey("questions.id"), nullable=False)
    operator = Column(String(20), default="IN", nullable=False)
    trigger_values = Column(Text, nullable=False)  # JSON array e.g. '["no","partial"]'
    target_question_id = Column(Integer, ForeignKey("questions.id"), nullable=False)
    make_required = Column(Boolean, default=False, nullable=False)

    questionnaire = relationship("Questionnaire", back_populates="conditional_rules")
    trigger_question = relationship("Question", foreign_keys=[trigger_question_id])
    target_question = relationship("Question", foreign_keys=[target_question_id])


VALID_CHOICES = ["yes", "no", "partial", "na"]

EVAL_MEETS = "MEETS_EXPECTATION"
EVAL_PARTIAL = "PARTIALLY_MEETS_EXPECTATION"
EVAL_DOES_NOT_MEET = "DOES_NOT_MEET_EXPECTATION"
EVAL_NO_EXPECTATION = "NO_EXPECTATION_DEFINED"


def compute_expectation_status(expected_value, answer_choice, expected_values=None, answer_mode="SINGLE"):
    """
    Compute evaluation status by comparing vendor answer to expected answer(s).
    Returns one of: EVAL_MEETS, EVAL_PARTIAL, EVAL_DOES_NOT_MEET, EVAL_NO_EXPECTATION
    
    For SINGLE mode: vendor answer must be in expected_set
    For MULTI mode: uses set intersection logic
    """
    import json
    
    # Build expected_set from expected_values (JSON) or fallback to single expected_value
    expected_set = set()
    if expected_values:
        try:
            parsed = json.loads(expected_values)
            if isinstance(parsed, list):
                expected_set = set(v.lower() for v in parsed if v)
        except (json.JSONDecodeError, TypeError):
            pass
    
    # Fallback to single expected_value if expected_values is empty
    if not expected_set and expected_value:
        expected_set = {expected_value.lower()}
    
    # No expectation defined
    if not expected_set:
        return EVAL_NO_EXPECTATION
    
    # No answer provided
    if not answer_choice:
        return EVAL_DOES_NOT_MEET
    
    if answer_mode == "MULTI":
        # Multi-select: answer_choice is comma-separated
        answers = set(a.strip().lower() for a in answer_choice.split(',') if a.strip())
        if not answers:
            return EVAL_DOES_NOT_MEET
        
        intersection = answers & expected_set
        
        if intersection and answers <= expected_set:
            # All selected answers are acceptable
            return EVAL_MEETS
        elif intersection:
            # Some acceptable, some not
            return EVAL_PARTIAL
        else:
            # No intersection - none of the selected answers are acceptable
            return EVAL_DOES_NOT_MEET
    else:
        # Single-select mode
        answer_lower = answer_choice.lower()
        
        if answer_lower in expected_set:
            return EVAL_MEETS
        
        # Partial meets if answer is "partial" and "yes" is expected
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


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
