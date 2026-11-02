import io
import os
import zipfile

from app.config import settings

from .conftest import PDF, device_for, login, make_church, make_user

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 100


def pdf(tag: str) -> bytes:
    return PDF + tag.encode()


def up(client, h, name, content, **form):
    return client.post("/api/v1/documents/inbox", headers=h, files={"file": (name, content)}, data=form)


def docx(text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", f"<w:document><w:body><w:p><w:t>{text}</w:t></w:p></w:body></w:document>")
    return buf.getvalue()


def admin_dev(client, root):
    h, _ = device_for(client, root, root, "PC admin")
    return h


def staff(client, root, email, role, **kw):
    make_user(client, root, email, role, **kw)
    u = login(client, email, "Passw0rd-long-1")
    h, _ = device_for(client, root, u, f"PC {email}")
    return h


def test_upload_needs_authorized_device(client, root):
    r = client.post("/api/v1/documents/inbox", headers=root, files={"file": ("a.pdf", PDF)})
    assert r.status_code == 403
    h, _ = device_for(client, root, root, approve=False)
    assert up(client, h, "a.pdf", PDF).status_code == 403
    assert up(client, admin_dev(client, root), "a.pdf", PDF).status_code == 201


def test_file_validation(client, root):
    h = admin_dev(client, root)
    assert up(client, h, "virus.exe", b"MZ" + b"0" * 50).status_code == 422
    assert up(client, h, "fake.pdf", PNG).status_code == 422                 # contenu != extension
    assert up(client, h, "empty.pdf", b"").status_code == 422
    assert up(client, h, "big.pdf", PDF + b"0" * (1024 * 1024 + 10)).status_code == 413
    assert up(client, h, "bin.txt", b"abc\x00def").status_code == 422
    assert up(client, h, "x.pdf", PDF, doc_type="inconnu").status_code == 422
    assert os.listdir(os.path.join(settings.storage_dir, "inbox")) == []     # rien ne reste d'un rejet


def test_path_traversal_filename_is_neutralised(client, root):
    h = admin_dev(client, root)
    r = up(client, h, "../../../etc/passwd.pdf", pdf("t"))
    assert r.status_code == 201 and r.json()["original_name"] == "passwd.pdf"
    files = os.listdir(os.path.join(settings.storage_dir, "inbox"))
    assert len(files) == 1 and files[0] == r.json()["id"]                    # nom généré, pas celui de l'utilisateur
    assert not os.path.exists("/etc/passwd.pdf")


def test_same_file_twice_is_not_staged_twice(client, root):
    h = admin_dev(client, root)
    a, b = up(client, h, "a.pdf", pdf("1")), up(client, h, "renamed.pdf", pdf("1"))
    assert (a.status_code, b.status_code) == (201, 200) and a.json()["id"] == b.json()["id"]
    assert len(client.get("/api/v1/documents/inbox", headers=h).json()) == 1


def test_one_click_organizes_and_flags_doubt(client, root):
    c1 = make_church(client, root)
    h = admin_dev(client, root)
    up(client, h, "Procès-verbal Église Baptiste de Pétion-Ville 2026.pdf", pdf("pv"))
    up(client, h, "Rapport annuel.pdf", pdf("rap"))
    up(client, h, "photo.png", PNG)
    up(client, h, "Certificat.pdf", pdf("cert"))
    up(client, h, "Rapport lettre.pdf", pdf("amb"))
    res = client.post("/api/v1/documents/inbox/organize", headers=h).json()
    by = {i["original_name"]: i for i in res["items"]}
    assert res["counts"] == {"organized": 2, "needs_review": 3}
    pv = by["Procès-verbal Église Baptiste de Pétion-Ville 2026.pdf"]
    assert pv["doc_type"] == "proces_verbal" and pv["church_id"] == c1["id"]
    assert by["Rapport annuel.pdf"]["doc_type"] == "rapport" and by["Rapport annuel.pdf"]["church_id"] is None
    assert "ambigu" in by["Rapport lettre.pdf"]["note"].lower()
    assert "église" in by["Certificat.pdf"]["note"].lower()
    # état physique : tampon vidé pour les classés, fichier en bibliothèque, restants toujours en tampon
    inbox = os.listdir(os.path.join(settings.storage_dir, "inbox"))
    assert len(inbox) == 3
    dl = client.get(f"/api/v1/documents/{pv['document_id']}/download", headers=root)
    assert dl.status_code == 200 and dl.content == pdf("pv") and "attachment" in dl.headers["content-disposition"]
    # relancer le clic : rien de nouveau, rien n'est détruit
    again = client.post("/api/v1/documents/inbox/organize", headers=h).json()
    assert again["counts"] == {}


def test_duplicate_of_classified_document(client, root):
    h = admin_dev(client, root)
    up(client, h, "Rapport 2025.pdf", pdf("same"))
    client.post("/api/v1/documents/inbox/organize", headers=h)
    up(client, h, "Rapport copie.pdf", pdf("same"))
    res = client.post("/api/v1/documents/inbox/organize", headers=h).json()
    assert res["counts"] == {"duplicate": 1}
    assert len(client.get("/api/v1/documents", headers=root).json()) == 1
    assert os.listdir(os.path.join(settings.storage_dir, "inbox")) == []


def test_classification_from_text_and_docx_content(client, root):
    c1 = make_church(client, root)
    h = admin_dev(client, root)
    up(client, h, "scan001.txt", "PROCÈS-VERBAL de l'assemblée de Église Baptiste de Pétion-Ville".encode())
    up(client, h, "doc2.docx", docx("Rapport financier — Église Baptiste de Pétion-Ville"))
    res = client.post("/api/v1/documents/inbox/organize", headers=h).json()
    types = sorted((i["doc_type"], i["church_id"]) for i in res["items"])
    assert types == [("proces_verbal", c1["id"]), ("rapport", c1["id"])]


def test_uploader_hints_and_manual_filing(client, root):
    c1 = make_church(client, root)
    h = admin_dev(client, root)
    r = up(client, h, "scan-sans-nom.pdf", pdf("m"), church_id=c1["id"], doc_type="certificat")
    res = client.post("/api/v1/documents/inbox/organize", headers=h).json()
    assert res["items"][0]["doc_type"] == "certificat" and res["items"][0]["church_id"] == c1["id"]
    up(client, h, "inconnu.pdf", pdf("n"))
    res = client.post("/api/v1/documents/inbox/organize", headers=h).json()
    item = res["items"][0]
    assert item["status"] == "needs_review"
    bad = client.post(f"/api/v1/documents/inbox/{item['item_id']}/file", headers=h, json={"doc_type": "certificat"})
    assert bad.status_code == 422                                           # certificat sans église
    ok = client.post(f"/api/v1/documents/inbox/{item['item_id']}/file", headers=h,
                     json={"doc_type": "lettre_officielle", "title": "Lettre au ministère"})
    assert ok.status_code == 200 and ok.json()["title"] == "Lettre au ministère"


def test_undo_batch_restores_inbox(client, root):
    h = admin_dev(client, root)
    up(client, h, "Rapport A.pdf", pdf("a"))
    up(client, h, "Rapport B.pdf", pdf("b"))
    res = client.post("/api/v1/documents/inbox/organize", headers=h).json()
    assert res["counts"] == {"organized": 2}
    assert len(os.listdir(os.path.join(settings.storage_dir, "inbox"))) == 0
    assert client.post(f"/api/v1/documents/inbox/batches/{res['batch_id']}/undo", headers=h).json() == {"restored": 2}
    assert client.get("/api/v1/documents", headers=root).json() == []
    assert len(os.listdir(os.path.join(settings.storage_dir, "inbox"))) == 2
    assert {i["status"] for i in client.get("/api/v1/documents/inbox", headers=h).json()} == {"staged"}
    assert client.post("/api/v1/documents/inbox/organize", headers=h).json()["counts"] == {"organized": 2}  # reclassable


def test_missing_staged_file_does_not_block_others(client, root):
    h = admin_dev(client, root)
    gone = up(client, h, "Rapport perdu.pdf", pdf("lost")).json()
    up(client, h, "Rapport ok.pdf", pdf("fine"))
    os.remove(os.path.join(settings.storage_dir, "inbox", gone["id"]))
    res = client.post("/api/v1/documents/inbox/organize", headers=h).json()
    assert res["counts"] == {"error": 1, "organized": 1}


def test_scopes_for_department_manager_and_church_admin(client, root):
    c1 = make_church(client, root)                                           # Ouest
    c2 = make_church(client, root, official_name="Église du Nord", department="Nord", commune="Cap-Haïtien")
    hroot = admin_dev(client, root)
    hdept = staff(client, root, "dept@fph.org", "dept_manager", department="Ouest")
    up(client, hroot, "Certificat Église du Nord.pdf", pdf("n1"))            # nom d'une église hors périmètre
    up(client, hroot, "Rapport général.pdf", pdf("n2"))                      # national
    up(client, hroot, "Rapport Église Baptiste de Pétion-Ville.pdf", pdf("o1"))
    up(client, hroot, "Rapport nord.pdf", pdf("n3"), church_id=c2["id"])     # indice : église du Nord -> invisible
    res = client.post("/api/v1/documents/inbox/organize", headers=hdept).json()
    by = {i["original_name"]: i for i in res["items"]}
    assert "Rapport nord.pdf" not in by                                      # hors périmètre : jamais vu
    assert by["Rapport rapport Église Baptiste de Pétion-Ville.pdf".replace("Rapport rapport", "Rapport")]["status"] == "organized"
    assert by["Certificat Église du Nord.pdf"]["status"] == "needs_review"   # pas rangé dans le Nord
    assert by["Rapport général.pdf"]["status"] == "needs_review"             # classement national réservé
    # l'élément du Nord reste en attente pour le niveau national
    assert any(i["original_name"] == "Rapport nord.pdf" and i["status"] == "staged"
               for i in client.get("/api/v1/documents/inbox", headers=hroot).json())
    # lecture : l'administrateur de l'église 2 ne voit pas le document de l'église 1
    doc1 = next(i for i in res["items"] if i["status"] == "organized")["document_id"]
    hadm2 = staff(client, root, "adm2@fph.org", "church_admin", church_id=c2["id"])
    assert client.get(f"/api/v1/documents/{doc1}", headers=hadm2).status_code == 404
    assert client.get(f"/api/v1/documents/{doc1}/download", headers=hadm2).status_code == 404
    assert client.get("/api/v1/documents", headers=hadm2).json() == []
    hadm1 = staff(client, root, "adm1@fph.org", "church_admin", church_id=c1["id"])
    assert client.get(f"/api/v1/documents/{doc1}/download", headers=hadm1).status_code == 200
    assert client.post("/api/v1/documents/inbox/organize", headers=hadm1).status_code == 403
    # un document national n'est pas lisible par un administrateur d'église
    again = client.post("/api/v1/documents/inbox/organize", headers=hroot, json={"include_review": True}).json()
    by2 = {i["original_name"]: i for i in again["items"]}
    assert by2["Rapport général.pdf"]["status"] == "organized" and by2["Rapport général.pdf"]["church_id"] is None
    assert by2["Certificat Église du Nord.pdf"]["church_id"] == c2["id"]     # le national peut le ranger
    nat = [d for d in client.get("/api/v1/documents", headers=root).json() if d["church_id"] is None]
    assert nat and client.get(f"/api/v1/documents/{nat[0]['id']}", headers=hadm1).status_code == 404


def test_staged_items_visible_only_to_owner_and_organizers(client, root):
    c1 = make_church(client, root)
    ha = staff(client, root, "a@fph.org", "employee", church_id=c1["id"])
    hb = staff(client, root, "b@fph.org", "employee", church_id=c1["id"])
    item = up(client, ha, "mon-doc.pdf", pdf("mine")).json()
    assert [i["id"] for i in client.get("/api/v1/documents/inbox", headers=ha).json()] == [item["id"]]
    assert client.get("/api/v1/documents/inbox", headers=hb).json() == []
    assert client.delete(f"/api/v1/documents/inbox/{item['id']}", headers=hb).status_code == 404
    assert client.delete(f"/api/v1/documents/inbox/{item['id']}", headers=ha).status_code == 204
    assert os.listdir(os.path.join(settings.storage_dir, "inbox")) == []
    # indice vers une autre église : refusé
    c2 = make_church(client, root, official_name="Église Autre", commune="Jacmel")
    assert up(client, ha, "x.pdf", pdf("z"), church_id=c2["id"]).status_code == 404


def test_audit_trail_for_documents(client, root):
    h = admin_dev(client, root)
    up(client, h, "Rapport.pdf", pdf("au"))
    res = client.post("/api/v1/documents/inbox/organize", headers=h).json()
    client.get(f"/api/v1/documents/{res['items'][0]['document_id']}/download", headers=root)
    acts = {a["action"] for a in client.get("/api/v1/admin/audit?limit=100", headers=root).json()}
    assert {"document.staged", "document.organize", "document.downloaded"} <= acts
