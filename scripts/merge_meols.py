#!/usr/bin/env python3
"""Fusionne les deux registres MEOL (ancien + nouveau), sans doublons, puis les enregistre dans la
base (`server/fph_dev.db`) et affiche les fiches telles qu'elles sont en base après l'écriture.

    python scripts/merge_meols.py [--dry-run]

Un doublon = même `match_key` (nom minuscule, sans accents ni ponctuation), la clé utilisée par
`import_meols.compare`. À égalité, la fiche du NOUVEAU registre gagne : c'est la source la plus
récente. La déduplication se fait aussi bien entre les deux registres qu'à l'intérieur du nouveau
(le registre connu en contient un : « Mission de la Renaissance Internationale »).

L'écriture passe par `import_meols.import_entries` : idempotente, elle laisse trace dans
`entity_history` et `audit_log`, et toute fiche importée reste `draft`.
"""
import argparse
import os
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
for _flux in (sys.stdout, sys.stderr):
    if hasattr(_flux, "reconfigure"):
        _flux.reconfigure(encoding="utf-8", errors="replace")

import import_meols as im  # noqa: E402

OLD_PDF = os.path.join(ROOT, "Liste_Meols_ancien_moderne.pdf")
NEW_PDF = os.path.join(ROOT, "Liste_Meols_nouveau_moderne.pdf")


def merge(old, new):
    """-> (entrées fusionnées sans doublon, doublons écartés). Nouveau prioritaire sur ancien."""
    by_key, dropped = {}, []
    for source, entries in (("ancien", old), ("nouveau", new)):
        for e in entries:
            kept = by_key.get(e["match_key"])
            if kept is None:
                by_key[e["match_key"]] = e
                continue
            # Le perdant est consigné avec ce que le gagnant ignore de lui, pour relecture humaine.
            loser = (e, kept) if source == "ancien" else (kept, e)
            dropped.append({"name": e["name"], "source": source,
                            "winner": kept["name"] if source == "ancien" else e["name"],
                            "winner_source": "nouveau" if source == "ancien" else "nouveau",
                            "winner_people": list(loser[1]["people"]), "loser": loser[0]})
            if source == "nouveau":
                by_key[e["match_key"]] = e
    return list(by_key.values()), dropped


def show_db_rows(name_keys):
    """Relit la base après l'import, pour les fiches du registre fusionné : ce qui y est réellement,
    pas ce qu'on croyait écrire. On filtre par `name_key` et non par horodatage : un rejeu ne doit
    pas afficher une liste amputée des fiches déjà entrées lors d'un précédent passage."""
    sys.path.insert(0, os.path.join(ROOT, "server"))
    from sqlalchemy import func, select

    from app.db import SessionLocal
    from app.models import Leader, Organization
    with SessionLocal() as db:
        rows = db.execute(
            select(Organization.name, Organization.org_type, Organization.department,
                   Organization.commune, Organization.validation_status,
                   func.count(Leader.id))
            .where(Organization.name_key.in_(name_keys))
            .outerjoin(Leader, Leader.organization_id == Organization.id)
            .group_by(Organization.id)
            .order_by(Organization.department, func.lower(Organization.name))
        ).all()
        # Contrôle : deux lignes de même name_key en base = doublon écrit malgré tout.
        dupes = db.execute(
            select(Organization.name_key, func.count()).group_by(Organization.name_key)
            .having(func.count() > 1)
        ).all()
    return rows, dupes


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="comparaison sans écriture en base")
    ap.add_argument("--as", dest="actor", default=None, help="compte auteur de l'import (défaut : Admin)")
    args = ap.parse_args(argv)

    old, _ = im.load(OLD_PDF)
    new, _ = im.load(NEW_PDF)
    entries, dropped = merge(old, new)

    from_old = sum(1 for e in entries if not any(e is n for n in new))
    print(f"Registre ancien : {len(old)} entrées · registre nouveau : {len(new)} entrées")
    print(f"Fusion sans doublons : {len(entries)} entrées "
          f"({from_old} apportées par l'ancien, {len(old) - from_old} présentes aussi dans le nouveau)")
    # Doublons internes au nouveau registre (mêmes clés vues deux fois) : la fusion n'en garde qu'une.
    seen = Counter(e["match_key"] for e in new)
    internes = sorted({e["name"] for e in new if seen[e["match_key"]] > 1})
    if internes:
        print(f"Doublons internes au nouveau registre (gardés une seule fois) : {len(internes)}")
        for n in internes:
            print(f"    - {n}")
    # Conflits entre registres où l'ancien apportait des infos que le nouveau n'a pas : à relire.
    enrichis = [d for d in dropped if d["source"] == "ancien"
                and (not d["winner_people"] and d["loser"]["people"])]
    if enrichis:
        print(f"Fiches écrasées où l'ancien nommait des responsables absents du nouveau : {len(enrichis)}")
        for d in enrichis:
            print(f"    - {d['name']} : {' / '.join(p for p in d['loser']['people'])}")

    if args.dry_run:
        print("\n--dry-run : rien n'est écrit en base.")
        return 0

    db_url = os.environ.get("FPH_DATABASE_URL") or im._DEFAULT_DB
    os.environ["FPH_DATABASE_URL"] = db_url
    summary, review = im.import_entries(entries, args.actor or "Admin", dry_run=False)
    print(f"\nBase : {db_url}")
    for label in ("organisations créées", "organisations mises à jour", "organisations inchangées",
                  "responsables créés", "responsables mis à jour"):
        print(f"  {label} : {summary[label]}")
    print(f"  entrées à vérifier : {len(review)}")

    rows, dupes = show_db_rows([e["name_key"] for e in entries])
    print(f"\nFiches en base après enregistrement : {len(rows)}")
    current = None
    for name, otype, dept, commune, status, nleaders in rows:
        if dept != current:
            current = dept
            print(f"\n[{dept}]")
        place = f", {commune}" if commune else ""
        print(f"  {name}  ({otype}{place}, {status}, {nleaders} responsable(s))")
    if dupes:
        print("\nATTENTION — doublons trouvés en base (même name_key) :", file=sys.stderr)
        for key, count in dupes:
            print(f"    - {key} : {count} lignes", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
