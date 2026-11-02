from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require
from ..models import AuditLog

router = APIRouter(prefix="/api/v1/admin", tags=["Administration"])


@router.get("/audit")
def audit_entries(action: str | None = None, limit: int = Query(default=50, ge=1, le=500),
                  _=Depends(require("audit:read")), db: Session = Depends(get_db)):
    stmt = select(AuditLog).order_by(AuditLog.at.desc()).limit(limit)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    return [{"id": a.id, "actor_id": a.actor_id, "action": a.action, "target_type": a.target_type,
             "target_id": a.target_id, "detail": a.detail, "request_id": a.request_id,
             "at": a.at.isoformat()} for a in db.scalars(stmt)]
