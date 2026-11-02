"""Configuration lue depuis les variables d'environnement (voir .env.example)."""
import os


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


class Settings:
    def __init__(self) -> None:
        self.database_url = os.environ.get("FPH_DATABASE_URL", "sqlite:///./fph_dev.db")
        self.secret_key = os.environ.get("FPH_SECRET_KEY", "")
        self.env = os.environ.get("FPH_ENV", "dev")
        self.access_ttl_minutes = _int("FPH_ACCESS_TTL_MINUTES", 30)
        self.max_failed_logins = _int("FPH_MAX_FAILED_LOGINS", 5)
        self.lock_minutes = _int("FPH_LOCK_MINUTES", 15)
        self.storage_dir = os.environ.get("FPH_STORAGE_DIR", "./storage")
        self.max_upload_mb = _int("FPH_MAX_UPLOAD_MB", 20)
        self.device_online_seconds = _int("FPH_DEVICE_ONLINE_SECONDS", 90)
        self.max_print_mb = _int("FPH_MAX_PRINT_MB", 20)
        self.print_expiry_hours = _int("FPH_PRINT_EXPIRY_HOURS", 24)      # travail en attente trop longtemps = erreur
        self.print_lease_seconds = _int("FPH_PRINT_LEASE_SECONDS", 300)   # délai accordé à l'agent avant reprise
        self.print_max_attempts = _int("FPH_PRINT_MAX_ATTEMPTS", 3)
        self.print_max_active_per_user = _int("FPH_PRINT_MAX_ACTIVE", 20)
        self.bootstrap_email = os.environ.get("FPH_BOOTSTRAP_ADMIN_EMAIL", "")
        self.bootstrap_username = os.environ.get("FPH_BOOTSTRAP_ADMIN_USERNAME", "")
        # Le compte initial doit changer son mot de passe à la 1re connexion (désactivable en test)
        self.bootstrap_force_change = os.environ.get("FPH_BOOTSTRAP_FORCE_CHANGE", "1") == "1"
        self.bootstrap_password = os.environ.get("FPH_BOOTSTRAP_ADMIN_PASSWORD", "")
        if not self.secret_key:
            if self.env == "prod":
                raise RuntimeError("FPH_SECRET_KEY est obligatoire en production")
            self.secret_key = "dev-only-insecure-key-change-me-0123456789"


settings = Settings()
