"""Vendor document upload service.

Handles validation and storage of vendor-level documents (SOC2, contracts, etc.).
Follows the same pattern as evidence_service.py.
"""

import os
import re
import uuid


ALLOWED_EXTENSIONS = {"pdf", "docx", "xlsx", "png", "jpg", "jpeg", "csv", "txt", "zip"}
MAX_FILE_SIZE = 25 * 1024 * 1024  # 25MB
UPLOAD_DIR = "uploads/vendor_documents"


def _sanitize_filename(filename: str) -> str:
    filename = os.path.basename(filename)
    filename = re.sub(r'[^\w\s\-\.]', '', filename)
    filename = filename.strip()
    if not filename:
        filename = "file"
    return filename


def _get_file_extension(filename: str) -> str:
    if '.' in filename:
        return filename.rsplit('.', 1)[1].lower()
    return ""


def validate_document_upload(filename: str, size: int) -> str | None:
    """Validate file extension and size. Returns error message or None if valid."""
    ext = _get_file_extension(filename)
    if ext not in ALLOWED_EXTENSIONS:
        return f"File type not allowed. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
    if size > MAX_FILE_SIZE:
        return "File too large. Maximum size is 25MB."
    return None


def store_vendor_document(
    file_content: bytes,
    original_filename: str,
    vendor_id: int,
) -> tuple[str, str, str]:
    """Store a vendor document on disk.

    Returns (sanitized_filename, stored_filename, stored_path).
    """
    upload_path = os.path.join(UPLOAD_DIR, str(vendor_id))
    os.makedirs(upload_path, exist_ok=True)

    safe_name = _sanitize_filename(original_filename)
    stored_filename = f"{uuid.uuid4().hex[:8]}_{safe_name}"
    stored_path = os.path.join(upload_path, stored_filename)

    with open(stored_path, "wb") as f:
        f.write(file_content)

    return safe_name, stored_filename, stored_path
