from datetime import datetime
from sqlalchemy.orm import Session
from models import (
    Assessment,
    ASSESSMENT_STATUS_DRAFT,
    ASSESSMENT_STATUS_SENT,
    ASSESSMENT_STATUS_IN_PROGRESS,
    ASSESSMENT_STATUS_SUBMITTED,
    ASSESSMENT_STATUS_REVIEWED,
)


def transition_to_sent(db: Session, assessment: Assessment) -> bool:
    """Transition DRAFT → SENT. Returns True if transition occurred."""
    if assessment.status == ASSESSMENT_STATUS_DRAFT:
        assessment.status = ASSESSMENT_STATUS_SENT
        assessment.sent_at = datetime.utcnow()
        db.commit()
        return True
    return False


def transition_to_in_progress(db: Session, assessment: Assessment) -> bool:
    """Transition SENT → IN_PROGRESS. Returns True if transition occurred."""
    if assessment.status == ASSESSMENT_STATUS_SENT:
        assessment.status = ASSESSMENT_STATUS_IN_PROGRESS
        return True
    return False


def transition_to_submitted(db: Session, assessment: Assessment) -> bool:
    """Transition SENT/IN_PROGRESS → SUBMITTED. Returns True if transition occurred."""
    if assessment.status in [ASSESSMENT_STATUS_SENT, ASSESSMENT_STATUS_IN_PROGRESS]:
        assessment.status = ASSESSMENT_STATUS_SUBMITTED
        assessment.submitted_at = datetime.utcnow()
        return True
    return False


def transition_to_reviewed(db: Session, assessment: Assessment) -> bool:
    """Transition SUBMITTED → REVIEWED. Returns True if transition occurred."""
    if assessment.status == ASSESSMENT_STATUS_SUBMITTED:
        assessment.status = ASSESSMENT_STATUS_REVIEWED
        assessment.reviewed_at = datetime.utcnow()
        return True
    return False
