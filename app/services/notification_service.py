"""Internal analyst notification service."""

from sqlalchemy.orm import Session
from models import Notification


def create_notification(
    db: Session,
    notification_type: str,
    message: str,
    link: str | None = None,
    vendor_id: int | None = None,
    assessment_id: int | None = None,
) -> Notification:
    """Create a new notification."""
    notif = Notification(
        notification_type=notification_type,
        message=message,
        link=link,
        vendor_id=vendor_id,
        assessment_id=assessment_id,
    )
    db.add(notif)
    return notif


def get_unread_count(db: Session) -> int:
    """Return count of unread notifications."""
    return db.query(Notification).filter(Notification.is_read == False).count()


def get_recent_notifications(db: Session, limit: int = 15) -> list[Notification]:
    """Return recent notifications, newest first."""
    return db.query(Notification).order_by(
        Notification.is_read.asc(),
        Notification.created_at.desc(),
    ).limit(limit).all()


def mark_read(db: Session, notification_id: int) -> Notification | None:
    """Mark a single notification as read."""
    notif = db.query(Notification).filter(Notification.id == notification_id).first()
    if notif:
        notif.is_read = True
    return notif


def mark_all_read(db: Session) -> int:
    """Mark all unread notifications as read. Returns count updated."""
    count = db.query(Notification).filter(
        Notification.is_read == False
    ).update({"is_read": True})
    return count
