"""Internal comments service."""

from sqlalchemy.orm import Session
from models import Comment


def get_comments(db: Session, entity_type: str, entity_id: int) -> list[Comment]:
    """Return comments for an entity, newest first."""
    return db.query(Comment).filter(
        Comment.entity_type == entity_type,
        Comment.entity_id == entity_id,
    ).order_by(Comment.created_at.desc()).all()


def add_comment(db: Session, entity_type: str, entity_id: int, user_id: int, body: str) -> Comment:
    """Add a comment to an entity."""
    comment = Comment(
        entity_type=entity_type,
        entity_id=entity_id,
        user_id=user_id,
        body=body,
    )
    db.add(comment)
    return comment


def delete_comment(db: Session, comment_id: int, user_id: int) -> bool:
    """Delete a comment (only by its author or admin)."""
    comment = db.query(Comment).filter(Comment.id == comment_id).first()
    if not comment:
        return False
    if comment.user_id != user_id:
        return False
    db.delete(comment)
    return True
