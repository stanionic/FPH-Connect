from fastapi import APIRouter, Depends, Query
from ..registration_service import aware, registered_count
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Church, Event, Registration
from ..schemas import ChurchPublicOut

router = APIRouter(prefix="/api/v1/public", tags=["Public"])


@router.get("/churches", response_model=list[ChurchPublicOut])
def public_churches(department: str | None = None,
                    q: str | None = Query(default=None, max_length=100),
                    limit: int = Query(default=50, ge=1, le=200),
                    offset: int = Query(default=0, ge=0),
                    db: Session = Depends(get_db)):
    """Répertoire public : uniquement les églises au statut 'published' et affiliées."""
    stmt = select(Church).where(Church.validation_status == "published",
                                Church.affiliation_status == "affiliated")
    if department:
        stmt = stmt.where(Church.department == department)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(Church.official_name).like(like),
                              func.lower(Church.commune).like(like)))
    return db.scalars(stmt.order_by(Church.official_name).limit(limit).offset(offset)).all()


@router.get("/events")
def public_events(department: str | None = None, limit: int = Query(default=50, ge=1, le=200),
                  offset: int = Query(default=0, ge=0), db: Session = Depends(get_db)):
    """Événements publiés uniquement. Aucune donnée d'inscrit."""
    stmt = select(Event).where(Event.validation_status == "published")
    if department:
        stmt = stmt.where(Event.department == department)
    out = []
    for e in db.scalars(stmt.order_by(Event.starts_at).limit(limit).offset(offset)):
        left = None if e.capacity is None else max(0, e.capacity - registered_count(db, e.id))
        out.append({"id": e.id, "title": e.title, "description": e.description,
                    "starts_at": aware(e.starts_at).isoformat(),
                    "ends_at": aware(e.ends_at).isoformat() if e.ends_at else None,
                    "location": e.location, "department": e.department,
                    "registration_open": e.registration_open, "spots_left": left})
    return out
