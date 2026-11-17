from .conftest import PDF, login, make_user


def staff_headers(client, root, email, role):
    make_user(client, root, email, role)
    return login(client, email, "Passw0rd-long-1")


def user_id(client, root, email):
    users = client.get("/api/v1/users?limit=200", headers=root).json()
    return next(u["id"] for u in users if u["email"] == email)


def grant(client, root, email, permissions):
    r = client.put(f"/api/v1/users/{user_id(client, root, email)}/permissions",
                   headers=root, json={"permissions": permissions})
    assert r.status_code == 200, r.text
    return r.json()


def share(client, headers, name="note.pdf", content=PDF, **form):
    return client.post("/api/v1/documents/share", headers=headers,
                       files={"file": (name, content)}, data=form)


def test_sharing_is_closed_until_superadmin_grants_it(client, root):
    h = staff_headers(client, root, "citizen@example.org", "public")
    assert client.get("/api/v1/documents", headers=h).status_code == 403
    assert share(client, h).status_code == 403

    catalog = client.get("/api/v1/users/permissions/catalog", headers=root)
    assert catalog.status_code == 200
    assert {item["code"] for item in catalog.json()} >= {"document:share", "document:read"}

    granted = grant(client, root, "citizen@example.org", ["document:share", "document:read"])
    assert set(granted["extra_permissions"]) == {"document:share", "document:read"}
    assert "document:share" in granted["permissions"]

    assert client.get("/api/v1/documents", headers=h).status_code == 200
    assert share(client, h, message="Bonjour le réseau FPH").status_code == 201


def test_short_message_is_stored_and_visible_to_the_network(client, root):
    author = staff_headers(client, root, "author@example.org", "public")
    reader = staff_headers(client, root, "reader@example.org", "public")
    grant(client, root, "author@example.org", ["document:share", "document:read"])
    grant(client, root, "reader@example.org", ["document:read"])

    created = share(client, author, name="rapport.pdf", title="Rapport national",
                    message="Pour la réunion de lundi.").json()
    assert created["title"] == "Rapport national"
    assert created["share_note"] == "Pour la réunion de lundi."
    assert created["visibility"] == "network" and created["shared"] is True

    listing = client.get("/api/v1/documents", headers=reader)
    assert listing.status_code == 200
    found = next(d for d in listing.json() if d["id"] == created["id"])
    assert found["share_note"] == "Pour la réunion de lundi."
    download = client.get(f"/api/v1/documents/{created['id']}/download", headers=reader)
    assert download.status_code == 200 and download.content == PDF


def test_message_is_limited_to_500_characters(client, root):
    author = staff_headers(client, root, "long@example.org", "public")
    grant(client, root, "long@example.org", ["document:share", "document:read"])
    created = share(client, author, message="x" * 700).json()
    assert len(created["share_note"]) == 500


def test_only_author_or_superadmin_can_unshare(client, root):
    author = staff_headers(client, root, "owner@example.org", "public")
    reader = staff_headers(client, root, "visitor@example.org", "public")
    grant(client, root, "owner@example.org", ["document:share", "document:read"])
    grant(client, root, "visitor@example.org", ["document:read"])
    created = share(client, author, message="À retirer").json()

    assert client.delete(f"/api/v1/documents/{created['id']}", headers=reader).status_code == 403
    assert client.delete(f"/api/v1/documents/{created['id']}", headers=author).status_code == 204
    assert client.get(f"/api/v1/documents/{created['id']}/download", headers=root).status_code == 404


def test_permission_grant_is_superadmin_only(client, root):
    staff_headers(client, root, "national@example.org", "national_admin")
    national = login(client, "national@example.org", "Passw0rd-long-1")
    target = user_id(client, root, "national@example.org")
    denied = client.put(f"/api/v1/users/{target}/permissions", headers=national,
                        json={"permissions": ["document:share"]})
    assert denied.status_code == 403
    unknown = client.put(f"/api/v1/users/{target}/permissions", headers=root,
                         json={"permissions": ["document:hack"]})
    assert unknown.status_code == 422
