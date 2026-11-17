"""Impression de documents depuis le dossier connecté (partagé côté serveur).

Les utilisateurs approuvés (permission `print:use`) listent les fichiers du dossier, les
téléchargent et déclenchent la boîte de dialogue d'impression du navigateur ou du système.
Aucun travail n'est envoyé à un agent d'impression : le document sort sur l'imprimante du poste.
"""
import mimetypes
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..audit import audit
from ..config import settings
from ..db import get_db
from ..deps import request_id, require
from ..models import User

router = APIRouter(prefix="/api/v1/print-folder", tags=["Impression — dossier connecté"])

# Formats que le navigateur ou le système peuvent ouvrir et imprimer directement.
PRINTABLE_EXT = {"pdf", "png", "jpg", "jpeg", "txt", "html", "htm"}


def _root() -> Path:
    root = Path(settings.print_folder).expanduser()
    if not root.is_absolute():
        root = (Path.cwd() / root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _document(name: str) -> Path:
    """Résout un nom de fichier sans autoriser la traversée de répertoire."""
    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        raise HTTPException(404, "Document introuvable")
    root = _root()
    path = (root / name).resolve()
    if path.parent != root or not path.is_file():
        raise HTTPException(404, "Document introuvable")
    return path


def _size_label(size: int) -> str:
    if size < 1024:
        return f"{size} o"
    if size < 1024 * 1024:
        return f"{size / 1024:.0f} Ko"
    return f"{size / (1024 * 1024):.1f} Mo"


@router.get("")
def list_documents(q: str | None = Query(default=None, max_length=100),
                   user: User = Depends(require("print:use"))):
    """Documents du dossier connecté que cet utilisateur approuvé peut imprimer."""
    root = _root()
    documents = []
    for path in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        if not path.is_file() or path.name.startswith("."):
            continue
        extension = path.suffix.lower().lstrip(".")
        if extension not in PRINTABLE_EXT:
            continue
        if q and q.lower() not in path.name.lower():
            continue
        stat = path.stat()
        documents.append({
            "name": path.name,
            "extension": extension,
            "size": stat.st_size,
            "size_label": _size_label(stat.st_size),
            "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            "mime": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            "download_url": f"/api/v1/print-folder/{quote(path.name)}",
        })
    return {"documents": documents, "count": len(documents)}


class PrintLogIn(BaseModel):
    copies: int = Field(default=1, ge=1, le=100)
    note: str | None = Field(default=None, max_length=500)


@router.post("/{name}/print")
def mark_printed(name: str, request: Request, body: PrintLogIn | None = None,
                 user: User = Depends(require("print:use")), db: Session = Depends(get_db)):
    """Trace l'impression demandée depuis le dossier connecté (le rendu est fait par le poste)."""
    path = _document(name)
    audit(db, user.id, "print_folder.printed", "document", path.name,
          {"copies": body.copies if body else 1, "note": body.note if body else None},
          request_id=request_id(request))
    db.commit()
    return {"name": path.name, "copies": body.copies if body else 1,
            "download_url": f"/api/v1/print-folder/{quote(path.name)}",
            "message": "Impression lancée depuis le dossier connecté."}


@router.get("/{name}")
def download_document(name: str, user: User = Depends(require("print:use"))):
    """Sert le document en ligne (inline) pour l'ouverture et l'impression côté poste."""
    path = _document(name)
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=mime, filename=path.name,
                        content_disposition_type="inline")
