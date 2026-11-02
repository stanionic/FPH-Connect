"""Règles communes de la file d'impression."""
from datetime import timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .documents import files as fs
from .models import Device, PrintGrant, PrintJob, Printer, User, now

TERMINAL = {"completed", "transmitted", "error", "cancelled"}
ACTIVE = {"pending", "accepted", "in_progress"}
LABELS = {"pending": "en attente", "accepted": "accepté", "in_progress": "en cours",
          "completed": "terminé", "transmitted": "transmis (fin non confirmable)",
          "error": "erreur", "cancelled": "annulé"}
PRINTABLE = {"pdf", "png", "jpg", "jpeg", "txt"}
DEFAULT_CAPS = {"duplex": False, "color": False, "paper": ["A4", "Letter"], "max_copies": 10, "tracking": "full"}


def aware(dt):
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def delete_file(job: PrintJob) -> None:
    if job.storage_path:
        try:
            fs.safe_path(job.storage_path).unlink(missing_ok=True)
        except (OSError, ValueError):
            pass
        job.storage_path = None


def finish(job: PrintJob, status: str, error: str | None = None) -> None:
    """État final : le document est supprimé du serveur (confidentialité)."""
    job.status, job.error = status, (error[:500] if error else None)
    job.completed_at = now()
    job.claim_expires_at = None
    delete_file(job)


def printer_online(db: Session, p: Printer) -> bool:
    d = db.get(Device, p.agent_device_id)
    return bool(d and d.status == "approved" and p.present and d.last_seen_at is not None
                and aware(d.last_seen_at) > now() - timedelta(seconds=settings.device_online_seconds))


def can_use(db: Session, user: User, p: Printer) -> bool:
    """Refus par défaut : imprimante activée ET (ouverte à tout le personnel OU accès accordé)."""
    if not p.enabled or "print:use" not in (user.role.permissions or []) or not user.is_active:
        return False
    if p.visibility == "all_staff":
        return True
    return db.scalar(select(PrintGrant.id).where(PrintGrant.printer_id == p.id,
                                                 PrintGrant.user_id == user.id)) is not None


def expire_stale(db: Session) -> int:
    """Un travail resté en attente trop longtemps ne doit pas sortir par surprise des jours plus tard."""
    limit = now() - timedelta(hours=settings.print_expiry_hours)
    n = 0
    for j in db.scalars(select(PrintJob).where(PrintJob.status == "pending")):
        if aware(j.created_at) < limit:
            finish(j, "error", "Expiré : imprimante restée hors ligne trop longtemps")
            n += 1
    if n:
        db.commit()
    return n


def recover_stale_claims(db: Session) -> int:
    """Un agent a pris le travail puis a disparu AVANT de confirmer l'envoi à l'imprimante :
    on le remet en file (au plus N tentatives). Dès qu'un identifiant côté imprimante est connu,
    il n'est plus repris automatiquement (évite l'impression en double)."""
    n = 0
    for j in db.scalars(select(PrintJob).where(PrintJob.status == "accepted",
                                               PrintJob.backend_job_id.is_(None),
                                               PrintJob.claim_expires_at.is_not(None))):
        if aware(j.claim_expires_at) < now():
            if j.attempts >= settings.print_max_attempts:
                finish(j, "error", "L'agent d'impression n'a pas confirmé la prise en charge")
            else:
                j.status, j.claim_expires_at = "pending", None
            n += 1
    if n:
        db.commit()
    return n
