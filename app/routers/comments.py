"""Internal comments API router."""

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from models import get_db, NOTIF_COMMENT_ADDED, VALID_COMMENT_ENTITIES
from app.services.auth_service import require_login
from app.services.comment_service import get_comments, add_comment, delete_comment
from app.services.notification_service import create_notification

router = APIRouter()


def _entity_link(entity_type: str, entity_id: int) -> str:
    """Build the redirect URL for a comment's parent entity."""
    if entity_type == "vendor":
        return f"/vendors/{entity_id}"
    elif entity_type == "assessment":
        return f"/assessments/{entity_id}/decision"
    elif entity_type == "decision":
        return f"/assessments/{entity_id}/decision"
    elif entity_type == "remediation":
        return f"/remediations/{entity_id}"
    return "/"


@router.get("/api/comments/{entity_type}/{entity_id}")
def api_get_comments(
    entity_type: str,
    entity_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_login),
):
    """Return comments as JSON."""
    if entity_type not in VALID_COMMENT_ENTITIES:
        return {"comments": []}
    comments = get_comments(db, entity_type, entity_id)
    return {
        "comments": [
            {
                "id": c.id,
                "body": c.body,
                "user_name": c.user.display_name if c.user else "Unknown",
                "user_id": c.user_id,
                "created_at": c.created_at.strftime("%b %d, %Y %H:%M") if c.created_at else "",
                "is_mine": c.user_id == user.id,
            }
            for c in comments
        ]
    }


@router.post("/api/comments/{entity_type}/{entity_id}")
def api_add_comment(
    entity_type: str,
    entity_id: int,
    request: Request,
    body: str = Form(...),
    db: Session = Depends(get_db),
    user=Depends(require_login),
):
    """Add a comment and redirect back."""
    if entity_type not in VALID_COMMENT_ENTITIES:
        return RedirectResponse("/", status_code=303)

    add_comment(db, entity_type, entity_id, user.id, body.strip())

    # Create notification
    create_notification(
        db,
        NOTIF_COMMENT_ADDED,
        f"{user.display_name} commented on {entity_type} #{entity_id}",
        link=_entity_link(entity_type, entity_id),
    )
    db.commit()

    redirect_url = _entity_link(entity_type, entity_id)
    return RedirectResponse(redirect_url, status_code=303)


@router.post("/api/comments/{comment_id}/delete")
def api_delete_comment(
    comment_id: int,
    entity_type: str = Form(""),
    entity_id: int = Form(0),
    request: Request = None,
    db: Session = Depends(get_db),
    user=Depends(require_login),
):
    """Delete a comment."""
    delete_comment(db, comment_id, user.id)
    db.commit()
    redirect_url = _entity_link(entity_type, entity_id)
    return RedirectResponse(redirect_url, status_code=303)
