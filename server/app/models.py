import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (JSON, Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, Index, Integer,
                        String, Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


class Role(Base):
    __tablename__ = "roles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    label: Mapped[str] = mapped_column(String(120))
    level: Mapped[int] = mapped_column(Integer)  # 0 = plus haut
    permissions: Mapped[list] = mapped_column(JSON, default=list)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("username", name="uq_users_username"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    username: Mapped[str | None] = mapped_column(String(50), nullable=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    full_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(300))
    role_id: Mapped[str] = mapped_column(ForeignKey("roles.id"))
    department: Mapped[str | None] = mapped_column(String(50), nullable=True)  # périmètre départemental
    church_id: Mapped[str | None] = mapped_column(ForeignKey("churches.id", use_alter=True, name="fk_user_church"), nullable=True)
    organization_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id", use_alter=True, name="fk_user_org"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    role: Mapped[Role] = relationship(lazy="joined")


class AuthSession(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    device_label: Mapped[str | None] = mapped_column(String(120), nullable=True)


class LoginEvent(Base):
    __tablename__ = "login_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(255), index=True)
    success: Mapped[bool] = mapped_column(Boolean)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Church(Base):
    __tablename__ = "churches"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_church_dedupe"),
        Index("ix_church_department_status", "department", "validation_status"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    official_name: Mapped[str] = mapped_column(String(250))
    dedupe_key: Mapped[str] = mapped_column(String(400))
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    department: Mapped[str] = mapped_column(String(50))
    commune: Mapped[str] = mapped_column(String(100))
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    main_leader_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    validation_status: Mapped[str] = mapped_column(String(20), default="draft")
    affiliation_status: Mapped[str] = mapped_column(String(20), default="pending")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class ChurchHistory(Base):
    __tablename__ = "church_history"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    church_id: Mapped[str] = mapped_column(ForeignKey("churches.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(30))
    changes: Mapped[dict] = mapped_column(JSON, default=dict)
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(60), index=True)
    target_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class IdempotencyKey(Base):
    """Empêche les opérations en double (clé fournie par le client, ex. file de sync)."""
    __tablename__ = "idempotency_keys"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36))
    resource_id: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Integration(Base):
    """Un site cible (WordPress, Flask, générique). Le secret HMAC n'est PAS stocké :
    il est dérivé de FPH_SECRET_KEY + id + secret_version (voir integrations/protocol.py)."""
    __tablename__ = "integrations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    kind: Mapped[str] = mapped_column(String(20))            # wordpress | flask | generic
    base_url: Mapped[str] = mapped_column(String(500))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    mode: Mapped[str] = mapped_column(String(10), default="test")   # test (à blanc) | live
    secret_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OutboxItem(Base):
    """Journal de publication + file d'envoi (outbox transactionnelle).
    `id` est un numéro de séquence monotone : le site l'utilise pour ignorer les
    messages obsolètes ou arrivés dans le désordre."""
    __tablename__ = "outbox"
    __table_args__ = (Index("ix_outbox_due", "status", "next_attempt_at"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    integration_id: Mapped[str] = mapped_column(ForeignKey("integrations.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10), default="church", server_default="church")  # church | event
    church_id: Mapped[str] = mapped_column(String(36), index=True)   # id de l'entité (nom historique)
    church_version: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(10))           # upsert | remove
    payload: Mapped[dict] = mapped_column(JSON, default=dict)  # champs publics au moment de l'envoi
    status: Mapped[str] = mapped_column(String(15), default="pending")
    # pending | sent | failed | dead | dry_run | superseded
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Device(Base):
    """Machine du réseau FPH. Être découverte ne suffit jamais : statut 'approved' requis.
    Le jeton n'est stocké que sous forme de condensat SHA-256."""
    __tablename__ = "devices"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120))
    platform: Mapped[str] = mapped_column(String(30))
    token_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending|approved|revoked
    office: Mapped[str | None] = mapped_column(String(120), nullable=True)
    registered_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    assigned_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    is_agent: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")  # agent d'impression (sans utilisateur)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("sender_id", "client_ref", name="uq_message_client_ref"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sender_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    sender_device_id: Mapped[str | None] = mapped_column(ForeignKey("devices.id"), nullable=True)
    recipient_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    audience: Mapped[str] = mapped_column(String(10), default="direct")   # direct | all
    body: Mapped[str] = mapped_column(Text)
    client_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Document(Base):
    """Document classé dans la base institutionnelle. Le fichier est sur disque sous un nom
    généré (jamais le nom envoyé par l'utilisateur)."""
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("sha256", name="uq_document_sha256"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(300))
    doc_type: Mapped[str] = mapped_column(String(30), index=True)
    church_id: Mapped[str | None] = mapped_column(ForeignKey("churches.id"), nullable=True, index=True)
    original_name: Mapped[str] = mapped_column(String(255))
    mime: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_path: Mapped[str] = mapped_column(String(500))
    uploaded_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    organized_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    inbox_item_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class InboxItem(Base):
    """Zone tampon : document partagé en attente de classement (persistante sur disque,
    donc conservée en cas de coupure de courant)."""
    __tablename__ = "inbox_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    uploader_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    device_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    original_name: Mapped[str] = mapped_column(String(255))
    mime: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(15), default="staged", index=True)
    # staged | organized | needs_review | duplicate | error
    hint_church_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    hint_doc_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    suggested_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    suggested_church_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class EntityHistory(Base):
    """Historique des modifications (organisations, événements, responsables)."""
    __tablename__ = "entity_history"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    entity_type: Mapped[str] = mapped_column(String(20), index=True)
    entity_id: Mapped[str] = mapped_column(String(36), index=True)
    version: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(30))
    changes: Mapped[dict] = mapped_column(JSON, default=dict)
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Organization(Base):
    __tablename__ = "organizations"
    __table_args__ = (UniqueConstraint("name_key", name="uq_org_name_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(250))
    name_key: Mapped[str] = mapped_column(String(400))
    org_type: Mapped[str] = mapped_column(String(30))
    department: Mapped[str] = mapped_column(String(50), index=True)
    commune: Mapped[str | None] = mapped_column(String(100), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    validation_status: Mapped[str] = mapped_column(String(20), default="draft")
    affiliation_status: Mapped[str] = mapped_column(String(20), default="pending")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Leader(Base):
    """Pasteur ou responsable. Minimisation : pas de date de naissance, pas de pièce d'identité,
    pas d'adresse personnelle — uniquement ce qui sert à l'administration."""
    __tablename__ = "leaders"
    __table_args__ = (CheckConstraint("church_id IS NOT NULL OR organization_id IS NOT NULL",
                                      name="ck_leader_has_attachment"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    full_name: Mapped[str] = mapped_column(String(200))
    function: Mapped[str] = mapped_column(String(30))
    church_id: Mapped[str | None] = mapped_column(ForeignKey("churches.id"), nullable=True, index=True)
    organization_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
    professional_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    professional_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    admin_status: Mapped[str] = mapped_column(String(15), default="active")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class LeaderAssignment(Base):
    """Historique des nominations et affectations."""
    __tablename__ = "leader_assignments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    leader_id: Mapped[str] = mapped_column(ForeignKey("leaders.id"), index=True)
    church_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    organization_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    function: Mapped[str] = mapped_column(String(30))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    recorded_by: Mapped[str | None] = mapped_column(String(36), nullable=True)


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (Index("ix_event_dept_status", "department", "validation_status"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(250))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    location: Mapped[str | None] = mapped_column(String(300), nullable=True)
    department: Mapped[str | None] = mapped_column(String(50), nullable=True)  # None = national
    organizer_church_id: Mapped[str | None] = mapped_column(ForeignKey("churches.id"), nullable=True, index=True)
    organizer_org_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
    validation_status: Mapped[str] = mapped_column(String(20), default="draft")
    registration_open: Mapped[bool] = mapped_column(Boolean, default=False)
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    registration_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Registration(Base):
    """Inscription à un événement. Données personnelles : visibles des seuls responsables
    habilités ; effaçables (anonymisation) sur demande."""
    __tablename__ = "registrations"
    __table_args__ = (UniqueConstraint("event_id", "dedupe_key", name="uq_reg_person"),
                      UniqueConstraint("event_id", "idempotency_key", name="uq_reg_idem"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="staff")      # staff | site
    status: Mapped[str] = mapped_column(String(12), default="registered")
    # registered | waitlisted | cancelled | erased
    dedupe_key: Mapped[str] = mapped_column(String(300))
    idempotency_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    consent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Printer(Base):
    """Imprimante partagée par un agent. Découverte = désactivée : un administrateur doit l'activer
    puis accorder l'accès (jamais d'autorisation automatique)."""
    __tablename__ = "printers"
    __table_args__ = (UniqueConstraint("agent_device_id", "system_name", name="uq_printer_agent_queue"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120))
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    system_name: Mapped[str] = mapped_column(String(200))        # nom de la file sur le poste de l'agent
    agent_device_id: Mapped[str] = mapped_column(ForeignKey("devices.id"), index=True)
    backend: Mapped[str] = mapped_column(String(10))              # cups | windows | file
    capabilities: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    visibility: Mapped[str] = mapped_column(String(12), default="granted")   # granted | all_staff
    present: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PrintGrant(Base):
    __tablename__ = "print_grants"
    __table_args__ = (UniqueConstraint("printer_id", "user_id", name="uq_print_grant"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    printer_id: Mapped[str] = mapped_column(ForeignKey("printers.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    granted_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PrintJob(Base):
    """États : pending (en attente) | accepted (pris en charge par l'agent) | in_progress (en cours) |
    completed (terminé, confirmé) | transmitted (transmis, fin non confirmable) | error | cancelled.
    Le fichier est supprimé dès que le travail atteint un état final."""
    __tablename__ = "print_jobs"
    __table_args__ = (Index("ix_printjob_status_printer", "status", "printer_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    printer_id: Mapped[str] = mapped_column(ForeignKey("printers.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    device_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    original_name: Mapped[str] = mapped_column(String(255))
    mime: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    copies: Mapped[int] = mapped_column(Integer, default=1)
    options: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(12), default="pending")
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    backend_job_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    unknown_polls: Mapped[int] = mapped_column(Integer, default=0)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    claim_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
