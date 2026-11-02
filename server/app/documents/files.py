"""Stockage et validation des fichiers. Les fichiers sont toujours écrits sous un nom
généré ; le nom fourni par l'utilisateur ne sert que de métadonnée nettoyée."""
import os
import re
from pathlib import Path

from ..config import settings

DOC_TYPES = ["lettre_officielle", "proces_verbal", "rapport", "certificat",
             "document_affiliation", "archive_administrative"]
CHURCH_REQUIRED = {"certificat", "document_affiliation"}

ALLOWED = {  # extension -> (type MIME servi, signature(s) attendues)
    "pdf": ("application/pdf", [b"%PDF"]),
    "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", [b"PK\x03\x04"]),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", [b"PK\x03\x04"]),
    "odt": ("application/vnd.oasis.opendocument.text", [b"PK\x03\x04"]),
    "doc": ("application/msword", [b"\xd0\xcf\x11\xe0"]),
    "png": ("image/png", [b"\x89PNG"]),
    "jpg": ("image/jpeg", [b"\xff\xd8\xff"]),
    "jpeg": ("image/jpeg", [b"\xff\xd8\xff"]),
    "txt": ("text/plain", None),
}


def root() -> Path:
    p = Path(settings.storage_dir).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def safe_path(*parts: str) -> Path:
    p = root().joinpath(*parts).resolve()
    if root() not in p.parents:
        raise ValueError("chemin hors du stockage")
    return p


def inbox_path(item_id: str) -> Path:
    return safe_path("inbox", item_id)


def library_path(doc_type: str, church_id: str | None, year: int, doc_id: str) -> Path:
    return safe_path("library", doc_type, church_id or "national", str(year), doc_id)


def clean_filename(name: str) -> str:
    base = os.path.basename((name or "").replace("\\", "/"))
    base = re.sub(r"[\x00-\x1f\x7f]", "", base).strip().strip(".")
    return (base or "document")[:200]


def check_type(filename: str, head: bytes) -> tuple[str, str]:
    """Retourne (extension, mime) ou lève ValueError si le contenu ne correspond pas."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED:
        raise ValueError("Type de fichier non autorisé")
    mime, sigs = ALLOWED[ext]
    if sigs is None:
        if b"\x00" in head:
            raise ValueError("Le contenu ne correspond pas à un fichier texte")
    elif not any(head.startswith(s) for s in sigs):
        raise ValueError("Le contenu ne correspond pas à l'extension du fichier")
    return ext, mime
