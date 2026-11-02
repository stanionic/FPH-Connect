from sqlalchemy.orm import Session

from .models import AuditLog


def audit(db: Session, actor_id, action, target_type=None, target_id=None,
          detail=None, request_id=None):
    db.add(AuditLog(actor_id=actor_id, action=action, target_type=target_type,
                    target_id=target_id, detail=detail or {}, request_id=request_id))
