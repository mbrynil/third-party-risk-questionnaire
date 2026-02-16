import uuid
from sqlalchemy.orm import Session
from models import Assessment, AssessmentTemplate


def generate_unique_token(db: Session, max_retries: int = 5) -> str:
    """Generate a unique 8-character token, checking both assessments and templates."""
    for _ in range(max_retries):
        token = str(uuid.uuid4())[:8]
        existing_assessment = db.query(Assessment).filter(Assessment.token == token).first()
        existing_template = db.query(AssessmentTemplate).filter(AssessmentTemplate.token == token).first()
        if not existing_assessment and not existing_template:
            return token
    return token
