"""TLS du réseau local : génération des certificats, vérifications réelles, lanceur sécurisé."""
import datetime as dt
import http.server
import json
import os
import ssl
import stat
import threading

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID

import make_lan_certs as mk
from app import serve
from fph_agent.client import AgentClient
from fph_agent.client import NetworkError as AgentNetworkError
from fph_client.api import ApiClient, NetworkError
from fph_client.tls import make_verify
from fph_flask_connector import forward_registration


@pytest.fixture()
def certs(tmp_path):
    out = str(tmp_path / "certs")
    r = mk.generate(out, names=["fph-serveur.local"], ips=["127.0.0.1"])
    return out, r


def load(path):
    with open(path, "rb") as f:
        return x509.load_pem_x509_certificate(f.read())


class _H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _reply(self):
        body = json.dumps({"status": "ok", "path": self.path}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._reply()

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self._reply()


@pytest.fixture()
def https_server(certs):
    out, _ = certs
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _H)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(os.path.join(out, "server.pem"), os.path.join(out, "server.key"))
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv.server_address[1]
    srv.shutdown()
    srv.server_close()


# ---------- génération ----------
def test_generated_certificates_are_well_formed(certs):
    out, r = certs
    ca, srv = load(f"{out}/ca.pem"), load(f"{out}/server.pem")
    assert r["ca_created"] and len(r["ca_fingerprint"].split(":")) == 32
    assert ca.extensions.get_extension_for_class(x509.BasicConstraints).value.ca is True
    bc = srv.extensions.get_extension_for_class(x509.BasicConstraints).value
    assert bc.ca is False                                                 # le certificat serveur ne peut pas signer d'autres certificats
    san = srv.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert [str(i) for i in san.get_values_for_type(x509.IPAddress)] == ["127.0.0.1"]
    assert san.get_values_for_type(x509.DNSName) == ["fph-serveur.local"]
    assert ExtendedKeyUsageOID.SERVER_AUTH in srv.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    assert srv.issuer == ca.subject
    ca.public_key().verify(srv.signature, srv.tbs_certificate_bytes, ec.ECDSA(srv.signature_hash_algorithm))  # signé par l'autorité
    days = (srv.not_valid_after_utc - srv.not_valid_before_utc).days
    assert days <= mk.MAX_SERVER_DAYS and srv.not_valid_after_utc > dt.datetime.now(dt.timezone.utc)


def test_private_keys_are_not_readable_by_others(certs):
    out, _ = certs
    for k in ("ca.key", "server.key"):
        assert stat.S_IMODE(os.stat(f"{out}/{k}").st_mode) == 0o600
    assert b"PRIVATE KEY" not in open(f"{out}/ca.pem", "rb").read()      # le fichier à distribuer ne contient pas de clé


def test_renewal_keeps_the_authority_and_force_replaces_it(certs):
    out, first = certs
    ca_before = open(f"{out}/ca.pem", "rb").read()
    srv_before = open(f"{out}/server.pem", "rb").read()
    again = mk.generate(out, names=["fph-serveur.local"], ips=["127.0.0.1"])
    assert again["ca_created"] is False and again["ca_fingerprint"] == first["ca_fingerprint"]
    assert open(f"{out}/ca.pem", "rb").read() == ca_before                # postes déjà configurés : rien à refaire
    assert open(f"{out}/server.pem", "rb").read() != srv_before           # nouveau certificat serveur
    forced = mk.generate(out, names=["fph-serveur.local"], ips=["127.0.0.1"], force=True)
    assert forced["ca_created"] is True and forced["ca_fingerprint"] != first["ca_fingerprint"]


def test_generator_rejects_bad_input(tmp_path):
    out = str(tmp_path / "c")
    for kw in ({}, {"ips": ["999.1.1.1"]}, {"names": ["pas valide!"]}, {"names": ["a_b"]}, {"names": ["x"], "days": 0},
               {"names": ["x"], "days": 5000}):
        with pytest.raises(ValueError):
            mk.generate(out, **kw)
    assert mk.main(["--out", out]) == 2                                   # pas de nom ni d'IP : erreur claire


# ---------- vérifications réelles ----------
def test_client_with_fph_ca_connects_and_validates(https_server, certs):
    out, _ = certs
    api = ApiClient(f"https://127.0.0.1:{https_server}", ca_file=f"{out}/ca.pem")
    assert api._req("GET", "/health")["status"] == "ok"                   # le client renvoie déjà le JSON décodé
    ag = AgentClient(f"https://127.0.0.1:{https_server}", "id:tok", ca_file=f"{out}/ca.pem")
    assert ag._req("GET", "/health").json()["status"] == "ok"


def test_unknown_authority_is_rejected(https_server, tmp_path):
    other = mk.generate(str(tmp_path / "other"), names=["x"], ips=["127.0.0.1"])   # une AUTRE autorité
    with pytest.raises(NetworkError) as e:
        ApiClient(f"https://127.0.0.1:{https_server}", ca_file=str(tmp_path / "other" / "ca.pem"))._req("GET", "/health")
    assert "CERTIFICATE_VERIFY_FAILED" in str(e.value)
    # sans autorité FPH : le magasin du système ne connaît pas notre autorité privée -> refus
    with pytest.raises(NetworkError) as e2:
        ApiClient(f"https://127.0.0.1:{https_server}")._req("GET", "/health")
    assert "CERTIFICATE_VERIFY_FAILED" in str(e2.value)
    with pytest.raises(AgentNetworkError):
        AgentClient(f"https://127.0.0.1:{https_server}", "id:tok")._req("GET", "/health")


def test_hostname_must_match_the_certificate(https_server, certs, tmp_path):
    out, _ = certs                                                        # certificat pour 127.0.0.1 et fph-serveur.local
    with pytest.raises(NetworkError) as e:                                # « localhost » n'est dans aucun SAN
        ApiClient(f"https://localhost:{https_server}", ca_file=f"{out}/ca.pem")._req("GET", "/health")
    assert "hostname" in str(e.value).lower() or "CERTIFICATE_VERIFY_FAILED" in str(e.value)


def test_plain_http_to_tls_port_fails(https_server):
    with pytest.raises(httpx.HTTPError):
        httpx.get(f"http://127.0.0.1:{https_server}/health", timeout=3)


def test_missing_ca_file_is_an_explicit_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        make_verify(str(tmp_path / "absent.pem"))                         # pas de repli silencieux sur « ne pas vérifier »


def test_site_tool_forwards_over_verified_tls(https_server, certs):
    out, _ = certs
    status, body = forward_registration(f"https://127.0.0.1:{https_server}", "integ", "s" * 40,
                                        {"event_id": "e"}, idempotency_key="k-0000001", ca_file=f"{out}/ca.pem")
    assert status == 200 and body["status"] == "ok" and body["path"].endswith("/api/v1/inbound/integ/registrations")
    with pytest.raises(Exception) as e:                                   # sans l'autorité : la vérification échoue
        forward_registration(f"https://127.0.0.1:{https_server}", "integ", "s" * 40, {"event_id": "e"})
    assert "CERTIFICATE_VERIFY_FAILED" in str(e.value)


# ---------- lanceur du serveur ----------
def test_production_refuses_to_start_without_tls(certs):
    out, _ = certs
    with pytest.raises(SystemExit) as e:
        serve.plan({"FPH_ENV": "prod"})
    assert "TLS" in str(e.value)
    kw, warns = serve.plan({"FPH_ENV": "prod", "FPH_BEHIND_TLS_PROXY": "1", "FPH_HOST": "127.0.0.1"})
    assert "ssl_certfile" not in kw and kw["host"] == "127.0.0.1" and warns == []   # proxy TLS déclaré + écoute locale : rien à signaler
    _, warns = serve.plan({"FPH_ENV": "prod", "FPH_BEHIND_TLS_PROXY": "1"})          # proxy déclaré mais serveur ouvert à tout le réseau
    assert len(warns) == 1 and "sans passer par le proxy" in warns[0]
    kw, warns = serve.plan({"FPH_ENV": "prod", "FPH_TLS_CERT": f"{out}/server.pem", "FPH_TLS_KEY": f"{out}/server.key"})
    assert kw["ssl_certfile"].endswith("server.pem") and kw["ssl_keyfile"].endswith("server.key") and warns == []


def test_dev_mode_warns_about_plain_http_and_tls_inputs_are_validated(certs, tmp_path):
    out, _ = certs
    kw, warns = serve.plan({})
    assert "ssl_certfile" not in kw and any("en clair" in w for w in warns)
    with pytest.raises(SystemExit):
        serve.plan({"FPH_TLS_CERT": f"{out}/server.pem"})                  # clé manquante
    with pytest.raises(SystemExit) as e:
        serve.plan({"FPH_TLS_CERT": f"{out}/nope.pem", "FPH_TLS_KEY": f"{out}/server.key"})
    assert "introuvable" in str(e.value)
    os.chmod(f"{out}/server.key", 0o644)
    _, warns = serve.plan({"FPH_TLS_CERT": f"{out}/server.pem", "FPH_TLS_KEY": f"{out}/server.key"})
    assert any("chmod 600" in w for w in warns)                           # clé trop lisible : avertissement
