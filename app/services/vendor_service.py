import re
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


def normalize_vendor_name(name: str) -> str:
    """Strip common suffixes and normalize for comparison."""
    name = name.strip().lower()
    suffixes = [
        r'\binc\.?\b', r'\bcorp\.?\b', r'\bllc\b', r'\bltd\.?\b',
        r'\bco\.?\b', r'\bcompany\b', r'\bgroup\b', r'\bholdings?\b',
        r'\binternational\b', r'\bglobal\b', r'\bsolutions?\b',
        r'\btechnolog(y|ies)\b', r'\bservices?\b', r'\bsystems?\b',
    ]
    for suffix in suffixes:
        name = re.sub(suffix, '', name)
    name = re.sub(r'[^a-z0-9\s]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def _bigrams(s: str) -> set:
    """Generate character bigrams from a string."""
    s = s.lower().replace(' ', '')
    if len(s) < 2:
        return {s}
    return {s[i:i+2] for i in range(len(s) - 1)}


def bigram_similarity(a: str, b: str) -> float:
    """Jaccard similarity using character bigrams."""
    ba = _bigrams(a)
    bb = _bigrams(b)
    if not ba or not bb:
        return 0.0
    intersection = ba & bb
    union = ba | bb
    return len(intersection) / len(union) if union else 0.0


def find_similar_vendors(db: Session, name: str, threshold: float = 0.5) -> list[dict]:
    """Find vendors with similar names using bigram Jaccard similarity."""
    normalized = normalize_vendor_name(name)
    if not normalized:
        return []

    vendors = db.query(Vendor).all()
    results = []
    for v in vendors:
        v_normalized = normalize_vendor_name(v.name)
        sim = bigram_similarity(normalized, v_normalized)
        if sim >= threshold:
            results.append({
                "id": v.id,
                "name": v.name,
                "similarity": round(sim, 2),
            })

    results.sort(key=lambda x: x["similarity"], reverse=True)
    return results[:5]
