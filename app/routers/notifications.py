"""Notification bell API endpoints."""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from models import get_db, NOTIF_ICONS, User
from app.services.notification_service import (
    get_unread_count, get_recent_notifications, mark_read, mark_all_read,
)
from app.services.auth_service import require_login

router = APIRouter()


@router.get("/api/notifications")
async def api_notifications(db: Session = Depends(get_db), current_user: User = Depends(require_login)):
    """Return recent notifications + unread count as JSON."""
    notifications = get_recent_notifications(db)
    unread = get_unread_count(db)
    return JSONResponse(content={
        "unread_count": unread,
        "notifications": [
            {
                "id": n.id,
                "type": n.notification_type,
                "message": n.message,
                "link": n.link,
                "is_read": n.is_read,
                "icon": NOTIF_ICONS.get(n.notification_type, "bi-bell"),
                "created_at": n.created_at.strftime("%b %d, %H:%M"),
            }
            for n in notifications
        ],
    })


@router.post("/api/notifications/{notification_id}/read")
async def api_mark_read(notification_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_login)):
    """Mark a notification as read and redirect to its link."""
    notif = mark_read(db, notification_id)
    db.commit()
    if notif and notif.link:
        return RedirectResponse(url=notif.link, status_code=303)
    return RedirectResponse(url="/", status_code=303)


@router.post("/api/notifications/read-all")
async def api_mark_all_read(db: Session = Depends(get_db), current_user: User = Depends(require_login)):
    """Mark all notifications as read."""
    mark_all_read(db)
    db.commit()
    return JSONResponse(content={"success": True})
