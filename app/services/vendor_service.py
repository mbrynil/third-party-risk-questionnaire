from sqlalchemy.orm import Session
from models import Vendor, VENDOR_STATUS_ACTIVE


def find_or_create_vendor(db: Session, company_name: str) -> Vendor:
    """Find existing vendor by name (case-insensitive) or create a new one."""
    vendor = db.query(Vendor).filter(
        Vendor.name.ilike(company_name)
    ).first()

    if not vendor:
        vendor = Vendor(
            name=company_name,
            status=VENDOR_STATUS_ACTIVE,
        )
        db.add(vendor)
        db.flush()

    return vendor
