import os
import re
import uuid


ALLOWED_EXTENSIONS = {"pdf", "docx", "xlsx", "png", "jpg", "jpeg"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
UPLOAD_DIR = "uploads"


def sanitize_filename(filename: str) -> str:
    """Sanitize filename to prevent path traversal and unsafe characters."""
    filename = os.path.basename(filename)
    filename = re.sub(r'[^\w\s\-\.]', '', filename)
    filename = filename.strip()
    if not filename:
        filename = "file"
    return filename


def get_file_extension(filename: str) -> str:
    """Get lowercase file extension without the dot."""
    if '.' in filename:
        return filename.rsplit('.', 1)[1].lower()
    return ""


def validate_upload(filename: str, file_size: int) -> str | None:
    """Validate file extension and size. Returns error message or None if valid."""
    ext = get_file_extension(filename)
    if ext not in ALLOWED_EXTENSIONS:
        return f"File type not allowed. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
    if file_size > MAX_FILE_SIZE:
        return "File too large. Maximum size is 10MB."
    return None


def store_file(
    file_content: bytes,
    original_filename: str,
    assessment_id: int,
    response_id: int,
) -> tuple[str, str, str]:
    """Store a file on disk. Returns (sanitized_filename, stored_filename, stored_path)."""
    upload_path = os.path.join(UPLOAD_DIR, str(assessment_id), str(response_id))
    os.makedirs(upload_path, exist_ok=True)

    safe_name = sanitize_filename(original_filename)
    stored_filename = f"{uuid.uuid4().hex[:8]}_{safe_name}"
    stored_path = os.path.join(upload_path, stored_filename)

    with open(stored_path, "wb") as f:
        f.write(file_content)

    return safe_name, stored_filename, stored_path
