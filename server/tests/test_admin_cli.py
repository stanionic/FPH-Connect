import pytest

from app import admin_cli

from .conftest import login

STRONG = "Zx9-Longue-Phrase-2026"


def run(*argv, password=STRONG, prompts=None):
    """Exécute l'outil comme un opérateur : mot de passe par l'environnement ou par saisie, sortie capturée."""
    out = []
    env = {"FPH_NEW_PASSWORD": password} if password is not None else {}
    answers = iter(prompts or [])
    code = admin_cli.main(list(argv), env=env, getpass_fn=lambda _p: next(answers), out=out.append)
    return code, "\n".join(out)


def test_create_superadmin_login_by_pseudo_and_forced_change(client):
    code, msg = run("create-superadmin", "--username", "Admin")
    assert code == 0 and "obligatoire" in msg
    for ident in ("Admin", "ADMIN", "admin"):                                     # insensible à la casse
        r = client.post("/api/v1/auth/login", json={"identifier": ident, "password": STRONG})
        assert r.status_code == 200
    h = login(client, "Admin", STRONG)
    me = client.get("/api/v1/auth/me", headers=h).json()
    assert me["role"] == "superadmin" and me["must_change_password"] is True
    assert client.get("/api/v1/churches", headers=h).status_code == 403            # bloqué tant que non changé
    code, _ = run("create-superadmin", "--username", "Admin2", "--keep")
    assert code == 0
    h2 = login(client, "Admin2", STRONG)
    assert client.get("/api/v1/churches", headers=h2).status_code == 200            # --keep : pas de changement imposé


def test_create_rejects_duplicates_weak_passwords_and_bad_names(client):
    assert run("create-superadmin", "--username", "Admin")[0] == 0
    assert run("create-superadmin", "--username", "admin")[0] == 1                  # même pseudo, autre casse
    assert run("create-superadmin", "--username", "Autre", "--email", "root@fph.org")[0] == 1   # e-mail déjà pris
    code, msg = run("create-superadmin", "--username", "Faible", password="court")
    assert code == 2 and "10 caractères" in msg
    assert run("create-superadmin", "--username", "Faible", password="1234567890123")[0] == 2   # que des chiffres
    assert run("create-superadmin", "--username", "a b")[0] == 2
    assert run("create-superadmin", "--username", "ab")[0] == 2
    assert client.post("/api/v1/auth/login", json={"identifier": "Faible", "password": "court"}).status_code == 401


def test_rename_keeps_password_and_frees_old_pseudo(client):
    code, msg = run("rename", "--user", "test-admin", "--to", "Admin")
    assert code == 0 and "n'est pas modifié" in msg
    assert client.post("/api/v1/auth/login", json={"identifier": "Admin", "password": "Root-Password-123"}).status_code == 200
    assert client.post("/api/v1/auth/login", json={"identifier": "test-admin", "password": "Root-Password-123"}).status_code == 401
    assert run("create-superadmin", "--username", "Autre")[0] == 0
    assert run("rename", "--user", "Autre", "--to", "admin")[0] == 1                # collision
    assert run("rename", "--user", "inconnu", "--to", "Nouveau")[0] == 1
    assert run("rename", "--user", "Autre", "--to", "x")[0] == 2


def test_reset_password_cuts_open_sessions_immediately(client, root):
    assert client.get("/api/v1/auth/me", headers=root).status_code == 200            # session ouverte (volée, par exemple)
    code, msg = run("reset-password", "--user", "test-admin")
    assert code == 0 and "1 session" in msg
    assert client.get("/api/v1/auth/me", headers=root).status_code == 401            # coupée aussitôt
    assert client.post("/api/v1/auth/login", json={"identifier": "test-admin", "password": "Root-Password-123"}).status_code == 401
    h = login(client, "test-admin", STRONG)
    assert client.get("/api/v1/auth/me", headers=h).json()["must_change_password"] is True
    assert run("reset-password", "--user", "personne")[0] == 1
    assert run("reset-password", "--user", "test-admin", password="court")[0] == 2
    assert login(client, "test-admin", STRONG)                                        # l'échec n'a rien changé


def test_unlock_after_lockout(client):
    for _ in range(3):
        client.post("/api/v1/auth/login", json={"identifier": "test-admin", "password": "faux"})
    assert client.post("/api/v1/auth/login", json={"identifier": "test-admin", "password": "Root-Password-123"}).status_code == 423
    assert run("unlock", "--user", "test-admin")[0] == 0
    assert client.post("/api/v1/auth/login", json={"identifier": "test-admin", "password": "Root-Password-123"}).status_code == 200


def test_password_is_never_an_argument_and_prompt_is_confirmed(client):
    for bad in (["--password", STRONG], ["--password=" + STRONG], ["-p", STRONG]):
        with pytest.raises(SystemExit) as e:
            run("create-superadmin", "--username", "Admin", *bad)
        assert e.value.code == 2                                                      # option inconnue : refusée par l'outil
    assert client.post("/api/v1/auth/login", json={"identifier": "Admin", "password": STRONG}).status_code == 401
    code, msg = run("create-superadmin", "--username", "Admin", password=None, prompts=[STRONG, "autre chose"])
    assert code == 2 and "différentes" in msg                                         # saisie de confirmation différente
    code, _ = run("create-superadmin", "--username", "Admin", password=None, prompts=[STRONG, STRONG])
    assert code == 0 and login(client, "Admin", STRONG)


def test_audit_records_actions_without_any_password(client, root):
    run("create-superadmin", "--username", "Admin")
    run("reset-password", "--user", "Admin", password="Autre-Phrase-Secrete-77")
    run("rename", "--user", "Admin", "--to", "Chef")
    h = login(client, "Chef", "Autre-Phrase-Secrete-77")
    # le super administrateur doit changer son mot de passe avant de lire l'audit
    client.post("/api/v1/auth/change-password", headers=h, json={"current_password": "Autre-Phrase-Secrete-77",
                                                                  "new_password": "Troisieme-Phrase-88x"})
    audit = str(client.get("/api/v1/admin/audit?limit=100", headers=h).json())
    assert "admin_cli.create_superadmin" in audit and "admin_cli.reset_password" in audit and "admin_cli.rename" in audit
    for secret in (STRONG, "Autre-Phrase-Secrete-77", "Troisieme-Phrase-88x"):
        assert secret not in audit
