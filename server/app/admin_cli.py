"""Outil d'exploitation à lancer SUR LE SERVEUR (accès au shell = confiance) :

  python -m app.admin_cli create-superadmin --username Admin
  python -m app.admin_cli reset-password    --user Admin
  python -m app.admin_cli rename            --user FPH-2026 --to Admin
  python -m app.admin_cli unlock            --user Admin

Le mot de passe n'est JAMAIS accepté en argument (il resterait dans l'historique du terminal et dans la liste des
processus) : il est lu dans la variable FPH_NEW_PASSWORD, ou saisi au clavier (deux fois).
Par défaut le compte devra changer son mot de passe à sa prochaine connexion (--keep pour l'éviter).
"""
import argparse
import getpass
import os
import re
import sys

from sqlalchemy import or_, select

from .audit import audit
from .db import SessionLocal
from .models import AuthSession, Role, User, now
from .permissions import ROLE_SEED
from .security import check_password_policy, hash_password

USERNAME = re.compile(r"^[A-Za-z0-9._-]{3,50}$")


def _ensure_roles(db) -> None:
    for code, label, level, perms in ROLE_SEED:
        if db.scalar(select(Role).where(Role.code == code)) is None:
            db.add(Role(code=code, label=label, level=level, permissions=perms))
    db.flush()


def _find(db, ident: str):
    ident = (ident or "").strip().lower()
    return db.scalar(select(User).where(or_(User.username == ident, User.email == ident))) if ident else None


def _read_password(env, getpass_fn) -> str:
    pw = env.get("FPH_NEW_PASSWORD")
    if pw is None:
        pw = getpass_fn("Nouveau mot de passe : ")
        if pw != getpass_fn("Confirmer le mot de passe : "):
            raise ValueError("Les deux saisies sont différentes")
    check_password_policy(pw)
    return pw


def _revoke_sessions(db, user_id: str) -> int:
    n = 0
    for s in db.scalars(select(AuthSession).where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))):
        s.revoked_at = now()
        n += 1
    return n


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m app.admin_cli", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create-superadmin")
    c.add_argument("--username", required=True)
    c.add_argument("--email")
    for name in ("reset-password", "unlock"):
        p = sub.add_parser(name)
        p.add_argument("--user", required=True, help="pseudo ou e-mail")
    r = sub.add_parser("rename")
    r.add_argument("--user", required=True)
    r.add_argument("--to", required=True)
    for name in ("create-superadmin", "reset-password"):
        sub.choices[name].add_argument("--keep", action="store_true",
                                       help="ne PAS imposer le changement du mot de passe à la prochaine connexion")
    return ap


def main(argv=None, env=None, getpass_fn=getpass.getpass, out=print) -> int:
    args = build_parser().parse_args(argv)            # toute option inconnue (ex. --password) => erreur argparse
    env = os.environ if env is None else env
    with SessionLocal() as db:
        try:
            if args.cmd == "create-superadmin":
                if not USERNAME.match(args.username):
                    raise ValueError("Pseudo invalide (3 à 50 caractères : lettres, chiffres, . _ -)")
                _ensure_roles(db)
                uname = args.username.lower()
                email = (args.email or f"{uname}@fph.local").lower()
                if _find(db, uname) or _find(db, email):
                    out("Erreur : ce pseudo ou cet e-mail existe déjà")
                    return 1
                pw = _read_password(env, getpass_fn)
                role = db.scalar(select(Role).where(Role.code == "superadmin"))
                u = User(email=email, username=uname, full_name="Superadministrateur", role_id=role.id,
                         password_hash=hash_password(pw), must_change_password=not args.keep)
                db.add(u)
                db.flush()
                audit(db, None, "admin_cli.create_superadmin", "user", u.id, {"username": uname})
                db.commit()
                out(f"Super administrateur « {args.username} » créé."
                    + ("" if args.keep else " Changement de mot de passe obligatoire à la première connexion."))
                return 0

            user = _find(db, args.user)
            if user is None:
                out("Erreur : utilisateur introuvable")
                return 1
            if args.cmd == "reset-password":
                user.password_hash = hash_password(_read_password(env, getpass_fn))
                user.must_change_password = not args.keep
                user.failed_logins, user.locked_until = 0, None
                n = _revoke_sessions(db, user.id)               # toute session ouverte est coupée immédiatement
                audit(db, None, "admin_cli.reset_password", "user", user.id, {"sessions_revoked": n})
                db.commit()
                out(f"Mot de passe de « {args.user} » remplacé ; {n} session(s) fermée(s)."
                    + ("" if args.keep else " Changement obligatoire à la prochaine connexion."))
            elif args.cmd == "rename":
                if not USERNAME.match(args.to):
                    raise ValueError("Pseudo invalide (3 à 50 caractères : lettres, chiffres, . _ -)")
                other = _find(db, args.to)
                if other is not None and other.id != user.id:
                    out("Erreur : ce pseudo est déjà pris")
                    return 1
                old, user.username = user.username, args.to.lower()
                audit(db, None, "admin_cli.rename", "user", user.id, {"from": old, "to": user.username})
                db.commit()
                out(f"Pseudo « {old} » remplacé par « {args.to} ». Le mot de passe n'est pas modifié.")
            elif args.cmd == "unlock":
                user.failed_logins, user.locked_until = 0, None
                audit(db, None, "admin_cli.unlock", "user", user.id)
                db.commit()
                out(f"Compte « {args.user} » déverrouillé.")
            return 0
        except ValueError as e:
            db.rollback()
            out(f"Erreur : {e}")
            return 2


if __name__ == "__main__":
    sys.exit(main())
