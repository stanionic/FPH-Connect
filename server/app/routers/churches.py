from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import audit
from ..db import get_db
from ..deps import get_current_user, request_id, require
from ..models import Church, ChurchHistory, IdempotencyKey, User
from ..permissions import forbid, has_permission, in_scope, scope_filter
from ..integrations.outbox import sync_church
from ..integrations.protocol import is_public
from ..schemas import ChurchCreate, ChurchOut, ChurchUpdate, HistoryOut, TransitionIn

router = APIRouter(prefix="/api/v1/churches", tags=["Églises"])

# action -> (statuts source, statut cible, permission requise)
TRANSITIONS = {
    "submit":   ({"draft"}, "pending", "church:submit"),
    "approve":  ({"pending"}, "approved", "church:approve"),
    "reject":   ({"pending"}, "draft", "church:approve"),
    "publish":  ({"approved"}, "published", "church:publish"),
    "withdraw": ({"published"}, "withdrawn", "church:publish"),
    "archive":  ({"draft", "approved", "withdrawn"}, "archived", "church:archive"),
}


def dedupe_key(name: str, commune: str) -> str:
    return f"{' '.join(name.lower().split())}|{' '.join(commune.lower().split())}"


def _history(db, church, action, changes, actor):
    db.add(ChurchHistory(church_id=church.id, version=church.version, action=action,
                         changes=changes, actor_id=actor.id))


def _get_scoped(db, church_id, user) -> Church:
    c = db.get(Church, church_id)
    # 404 (et non 403) hors périmètre : n'indique pas l'existence de l'objet
    if c is None or not in_scope(user, c):
        raise HTTPException(404, "Église introuvable")
    return c


@router.post("", response_model=ChurchOut, status_code=201)
def create_church(body: ChurchCreate, request: Request,
                  idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                  user: User = Depends(require("church:create")), db: Session = Depends(get_db)):
    if idempotency_key:
        prev = db.get(IdempotencyKey, idempotency_key)
        if prev and prev.user_id == user.id:
            existing = db.get(Church, prev.resource_id)
            if existing:
                return existing  # même opération rejouée : pas de doublon
    if user.role.code == "dept_manager" and body.department != user.department:
        forbid("Création hors de votre département")
    c = Church(**body.model_dump(), dedupe_key=dedupe_key(body.official_name, body.commune),
               created_by=user.id)
    db.add(c)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Une église de même nom existe déjà dans cette commune")
    if idempotency_key:
        db.add(IdempotencyKey(key=idempotency_key, user_id=user.id, resource_id=c.id))
    _history(db, c, "created", body.model_dump(mode="json"), user)
    audit(db, user.id, "church.created", "church", c.id, request_id=request_id(request))
    db.commit()
    return c


@router.get("", response_model=list[ChurchOut])
def list_churches(department: str | None = None, status: str | None = None,
                  q: str | None = Query(default=None, max_length=100),
                  limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0),
                  user: User = Depends(require("church:read")), db: Session = Depends(get_db)):
    stmt = select(Church)
    kind, val = scope_filter(user)
    if kind == "department":
        stmt = stmt.where(Church.department == val)
    elif kind == "church":
        stmt = stmt.where(Church.id == val)
    if department:
        stmt = stmt.where(Church.department == department)
    if status:
        stmt = stmt.where(Church.validation_status == status)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(Church.official_name).like(like),
                              func.lower(Church.commune).like(like)))
    return db.scalars(stmt.order_by(Church.official_name).limit(limit).offset(offset)).all()


@router.get("/{church_id}", response_model=ChurchOut)
def get_church(church_id: str, user: User = Depends(require("church:read")),
               db: Session = Depends(get_db)):
    return _get_scoped(db, church_id, user)


@router.patch("/{church_id}", response_model=ChurchOut)
def update_church(church_id: str, body: ChurchUpdate, request: Request,
                  user: User = Depends(require("church:update")), db: Session = Depends(get_db)):
    c = _get_scoped(db, church_id, user)
    if c.validation_status == "archived":
        raise HTTPException(409, "Une église archivée n'est pas modifiable")
    if body.version != c.version:
        raise HTTPException(409, detail={"message": "Conflit de version",
                                         "server_version": c.version})
    data = body.model_dump(exclude_unset=True, exclude={"version"})
    if (user.role.code == "dept_manager" and data.get("department")
            and data["department"] != user.department):
        forbid("Déplacement hors de votre département")
    changes = {k: v for k, v in data.items() if getattr(c, k) != v}
    if not changes:
        return c
    was_public = is_public(c)
    for k, v in changes.items():
        setattr(c, k, v)
    c.dedupe_key = dedupe_key(c.official_name, c.commune)
    # Toute modification de contenu invalide la validation : rien de non validé n'est public.
    if c.validation_status in ("approved", "published", "pending"):
        changes["validation_status"] = "pending"
        c.validation_status = "pending"
    c.version += 1
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Une église de même nom existe déjà dans cette commune")
    sync_church(db, c, was_public)  # retire du site si la fiche cesse d'être publique
    _history(db, c, "updated", {k: (v if not hasattr(v, "isoformat") else v.isoformat())
                                for k, v in changes.items()}, user)
    audit(db, user.id, "church.updated", "church", c.id, {"fields": list(changes)},
          request_id(request))
    db.commit()
    return c


@router.post("/{church_id}/transition", response_model=ChurchOut)
def transition(church_id: str, body: TransitionIn, request: Request,
               user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = _get_scoped(db, church_id, user)
    sources, target, perm = TRANSITIONS[body.action]
    if not has_permission(user, perm):
        forbid()
    if c.validation_status not in sources:
        raise HTTPException(409, f"Transition '{body.action}' impossible depuis "
                                 f"l'état '{c.validation_status}'")
    before = c.validation_status
    was_public = is_public(c)
    c.validation_status = target
    c.version += 1
    sync_church(db, c, was_public)
    _history(db, c, body.action, {"validation_status": [before, target]}, user)
    audit(db, user.id, f"church.{body.action}", "church", c.id,
          {"from": before, "to": target}, request_id(request))
    db.commit()
    return c


@router.get("/{church_id}/history", response_model=list[HistoryOut])
def history(church_id: str, user: User = Depends(require("church:read")),
            db: Session = Depends(get_db)):
    _get_scoped(db, church_id, user)
    return db.scalars(select(ChurchHistory).where(ChurchHistory.church_id == church_id)
                      .order_by(ChurchHistory.version, ChurchHistory.at)).all()
