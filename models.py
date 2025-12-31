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


class Questionnaire(Base):
    __tablename__ = "questionnaires"

    id = Column(Integer, primary_key=True, index=True)
    company_name = Column(String(255), nullable=False)
    title = Column(String(255), nullable=False)
    token = Column(String(64), unique=True, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    questions = relationship("Question", back_populates="questionnaire", cascade="all, delete-orphan")
    responses = relationship("Response", back_populates="questionnaire", cascade="all, delete-orphan")


class Question(Base):
    __tablename__ = "questions"

    id = Column(Integer, primary_key=True, index=True)
    questionnaire_id = Column(Integer, ForeignKey("questionnaires.id"), nullable=False)
    question_text = Column(Text, nullable=False)
    order = Column(Integer, default=0)

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


VALID_CHOICES = ["yes", "no", "partial", "na"]


def init_db():
    Base.metadata.create_all(bind=engine)


def seed_question_bank():
    db = SessionLocal()
    try:
        if db.query(QuestionBankItem).count() == 0:
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
            ]
            for category, text in default_questions:
                item = QuestionBankItem(category=category, text=text, is_active=True)
                db.add(item)
            db.commit()
    finally:
        db.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
