import uuid

from fastapi import FastAPI, Request
from sqlalchemy import select

from .config import settings
from .db import Base, SessionLocal, engine
from .models import Role, User
from .permissions import ROLE_SEED
from .routers import agent, audit_api, auth, churches, devices, documents, events, integrations, leaders, messages, organizations, printing, public, users
from .security import hash_password


def seed(db) -> None:
    for code, label, level, perms in ROLE_SEED:
        if db.scalar(select(Role).where(Role.code == code)) is None:
            db.add(Role(code=code, label=label, level=level, permissions=perms))
    db.flush()
    ident = settings.bootstrap_username or settings.bootstrap_email
    if ident and settings.bootstrap_password and db.scalar(select(User.id).limit(1)) is None:
        role = db.scalar(select(Role).where(Role.code == "superadmin"))
        username = settings.bootstrap_username.lower() or None
        email = (settings.bootstrap_email or f"{username}@fph.local").lower()
        db.add(User(email=email, username=username, full_name="Superadministrateur",
                    password_hash=hash_password(settings.bootstrap_password), role_id=role.id,
                    must_change_password=settings.bootstrap_force_change))
    db.commit()


def create_app(create_tables: bool = False) -> FastAPI:
    app = FastAPI(title="FPH Core Server", version="0.1.0",
                  description="API centrale de FPH Connect (prototype phase 1-2).")

    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response

    @app.on_event("startup")
    def _startup():
        if create_tables:  # dev/tests seulement ; en production : alembic upgrade head
            Base.metadata.create_all(engine)
        with SessionLocal() as db:
            seed(db)

    @app.get("/health", tags=["Système"])
    def health():
        return {"status": "ok"}

    for r in (auth.router, users.router, churches.router, public.router, audit_api.router,
              integrations.router, devices.router, devices.network, messages.router, documents.router,
              leaders.router, organizations.router, events.router, events.reg_router, events.inbound,
              printing.router, printing.admin, agent.router):
        app.include_router(r)
    return app


import os  # noqa: E402

app = create_app(create_tables=os.environ.get("FPH_CREATE_TABLES", "0") == "1")
