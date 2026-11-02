"""Classement automatique par règles simples et explicables (pas d'IA, pas d'OCR).
Principe : en cas de doute, ne pas ranger -> 'à vérifier'."""
import re
import unicodedata
import zipfile

KEYWORDS = {
    "proces_verbal": ["proces verbal", "pv", "minutes", "pwose verbal"],
    "lettre_officielle": ["lettre", "letter"],
    "rapport": ["rapport", "report", "rapo"],
    "certificat": ["certificat", "certificate", "setifika"],
    "document_affiliation": ["affiliation", "afilyasyon"],
}


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFKD", text)
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return f" {t.strip()} "


def types_in(text: str) -> set[str]:
    n = normalize(text)
    return {t for t, kws in KEYWORDS.items() if any(f" {k} " in n for k in kws)}


def content_head(path, ext: str, limit: int = 1000) -> str:
    """Début du texte pour .txt et .docx. Les PDF ne sont PAS lus (pas d'extraction de texte)."""
    try:
        if ext == "txt":
            with open(path, "rb") as f:
                return f.read(limit * 4).decode("utf-8", "ignore")[:limit]
        if ext == "docx":
            with zipfile.ZipFile(path) as z:
                xml = z.read("word/document.xml").decode("utf-8", "ignore")
            return re.sub(r"<[^>]+>", " ", xml)[:limit]
    except Exception:
        pass
    return ""


def match_church(text: str, churches) -> tuple[str | None, bool]:
    """(church_id, ambigu). Le nom officiel complet doit apparaître ; la plus longue
    correspondance gagne ; égalité entre deux églises différentes = ambigu."""
    n = normalize(text)
    hits = []
    for c in churches:
        cn = normalize(c.official_name)
        if len(cn.strip()) >= 6 and cn in n:
            hits.append((len(cn), c.id))
    if not hits:
        return None, False
    hits.sort(reverse=True)
    if len(hits) > 1 and hits[0][0] == hits[1][0]:
        return None, True
    return hits[0][1], False


def classify(filename: str, head: str, churches, hint_type=None, hint_church=None,
             allow_national: bool = True) -> dict:
    """Retourne {ok, doc_type, church_id, note}. ok=False => à vérifier par un humain."""
    stem = filename.rsplit(".", 1)[0]
    notes = []
    doc_type = hint_type
    if doc_type:
        notes.append("type indiqué par l'expéditeur")
    else:
        found = types_in(stem)
        if len(found) == 1:
            doc_type = next(iter(found))
        elif len(found) > 1:
            return {"ok": False, "doc_type": None, "church_id": None,
                    "note": f"Type ambigu dans le nom du fichier : {', '.join(sorted(found))}"}
        else:
            found = types_in(head[:500])
            if len(found) == 1:
                doc_type = next(iter(found))
                notes.append("type déduit du début du contenu")
    if doc_type is None:
        return {"ok": False, "doc_type": None, "church_id": None, "note": "Type de document non reconnu"}

    church_id = hint_church
    if church_id:
        notes.append("église indiquée par l'expéditeur")
    else:
        church_id, ambiguous = match_church(stem + " " + head, churches)
        if ambiguous:
            return {"ok": False, "doc_type": doc_type, "church_id": None,
                    "note": "Plusieurs églises possibles : à vérifier"}
        if church_id:
            notes.append("église reconnue par son nom")
    if doc_type in {"certificat", "document_affiliation"} and not church_id:
        return {"ok": False, "doc_type": doc_type, "church_id": None,
                "note": "Ce type de document doit être rattaché à une église"}
    if church_id is None and not allow_national:
        return {"ok": False, "doc_type": doc_type, "church_id": None,
                "note": "Aucune église reconnue : classement national réservé aux administrateurs nationaux"}
    return {"ok": True, "doc_type": doc_type, "church_id": church_id, "note": "; ".join(notes)}
