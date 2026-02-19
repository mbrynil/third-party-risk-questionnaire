"""Activity timeline service for vendor audit trail."""

from sqlalchemy.orm import Session
from models import VendorActivity


def log_activity(
    db: Session,
    vendor_id: int,
    activity_type: str,
    description: str,
    assessment_id: int | None = None,
    metadata_json: str | None = None,
    user_id: int | None = None,
):
    """Create a new activity record for a vendor."""
    activity = VendorActivity(
        vendor_id=vendor_id,
        activity_type=activity_type,
        description=description,
        assessment_id=assessment_id,
        metadata_json=metadata_json,
        user_id=user_id,
    )
    db.add(activity)
    return activity


def get_vendor_timeline(db: Session, vendor_id: int, limit: int = 50) -> list[VendorActivity]:
    """Return recent activities for a vendor, newest first."""
    return db.query(VendorActivity).filter(
        VendorActivity.vendor_id == vendor_id
    ).order_by(VendorActivity.created_at.desc()).limit(limit).all()
