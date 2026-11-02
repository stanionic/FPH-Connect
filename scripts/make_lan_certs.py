#!/usr/bin/env python3
"""Génère une petite autorité de certification FPH + le certificat TLS du serveur local.

  python scripts/make_lan_certs.py --out certs --ip 192.168.1.10 --name fph-serveur.local

Produit dans le dossier :
  ca.pem      certificat PUBLIC de l'autorité : à installer sur chaque poste/application (FPH_CA_CERT)
  ca.key      clé PRIVÉE de l'autorité : à garder HORS LIGNE (clé USB dans un coffre) après usage
  server.pem  certificat du serveur        server.key  clé privée du serveur (droits 0600)

Relancer la commande avec la même autorité = renouveler le certificat du serveur (ca.pem inchangé).
Le certificat n'est valable que pour les noms/adresses donnés : si l'IP du serveur change, en refaire un.
Dépendance : pip install -r scripts/requirements.txt
"""
import argparse
import datetime as dt
import ipaddress
import os
import re
import sys

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

_DNS = re.compile(r"^(?=.{1,253}$)([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$")
MAX_SERVER_DAYS = 825          # plafond accepté par les systèmes Apple ; raisonnable partout


def _write(path: str, data: bytes, private: bool) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600 if private else 0o644)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    if private:
        os.chmod(path, 0o600)


def _pem_key(key) -> bytes:
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())


def _validate(names, ips):
    if not names and not ips:
        raise ValueError("Indiquer au moins un --ip ou un --name")
    out_ips = []
    for i in ips:
        try:
            out_ips.append(ipaddress.ip_address(i))
        except ValueError:
            raise ValueError(f"Adresse IP invalide : {i}")
    for n in names:
        if not _DNS.match(n):
            raise ValueError(f"Nom de machine invalide : {n}")
    return out_ips


def fingerprint(cert) -> str:
    return ":".join(f"{b:02X}" for b in cert.fingerprint(hashes.SHA256()))


def generate(out_dir: str, names=(), ips=(), days: int = MAX_SERVER_DAYS, ca_days: int = 3650, force: bool = False):
    """Retourne {'ca_created': bool, 'ca_fingerprint': str, 'paths': {...}}."""
    ip_objs = _validate(list(names), list(ips))
    if not 1 <= days <= MAX_SERVER_DAYS:
        raise ValueError(f"--days doit être entre 1 et {MAX_SERVER_DAYS}")
    os.makedirs(out_dir, exist_ok=True)
    p = {k: os.path.join(out_dir, k) for k in ("ca.pem", "ca.key", "server.pem", "server.key")}
    now = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)      # tolère un léger décalage d'horloge
    ca_created = force or not (os.path.exists(p["ca.pem"]) and os.path.exists(p["ca.key"]))
    if ca_created:
        ca_key = ec.generate_private_key(ec.SECP256R1())
        subject = x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, "FPH Connect"),
                             x509.NameAttribute(NameOID.COMMON_NAME, "FPH Connect Local CA")])
        ca_cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
                   .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
                   .not_valid_before(now).not_valid_after(now + dt.timedelta(days=ca_days))
                   .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
                   .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                                content_commitment=False, key_encipherment=False, data_encipherment=False,
                                                key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
                   .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
                   .sign(ca_key, hashes.SHA256()))
        _write(p["ca.key"], _pem_key(ca_key), private=True)
        _write(p["ca.pem"], ca_cert.public_bytes(serialization.Encoding.PEM), private=False)
    else:
        with open(p["ca.key"], "rb") as f:
            ca_key = serialization.load_pem_private_key(f.read(), password=None)
        with open(p["ca.pem"], "rb") as f:
            ca_cert = x509.load_pem_x509_certificate(f.read())

    key = ec.generate_private_key(ec.SECP256R1())
    san = [x509.DNSName(n) for n in names] + [x509.IPAddress(i) for i in ip_objs]
    cn = (list(names) + [str(i) for i in ip_objs])[0]
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)]))
            .issuer_name(ca_cert.subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now).not_valid_after(now + dt.timedelta(days=days))
            .add_extension(x509.SubjectAlternativeName(san), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, key_encipherment=False, content_commitment=False,
                                         data_encipherment=False, key_agreement=False, key_cert_sign=False,
                                         crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_cert.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256()))
    _write(p["server.key"], _pem_key(key), private=True)
    _write(p["server.pem"], cert.public_bytes(serialization.Encoding.PEM), private=False)
    return {"ca_created": ca_created, "ca_fingerprint": fingerprint(ca_cert), "paths": p,
            "expires": (now + dt.timedelta(days=days)).date().isoformat()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="certs")
    ap.add_argument("--ip", action="append", default=[], help="adresse IP du serveur (répétable)")
    ap.add_argument("--name", action="append", default=[], help="nom de machine du serveur (répétable)")
    ap.add_argument("--days", type=int, default=MAX_SERVER_DAYS)
    ap.add_argument("--force", action="store_true", help="recréer aussi l'autorité (invalide tous les postes configurés)")
    a = ap.parse_args(argv)
    try:
        r = generate(a.out, a.name, a.ip, a.days, force=a.force)
    except ValueError as e:
        print(f"Erreur : {e}", file=sys.stderr)
        return 2
    print(f"Autorité {'CRÉÉE' if r['ca_created'] else 'réutilisée (inchangée)'} — empreinte SHA-256 :\n  {r['ca_fingerprint']}")
    print(f"Certificat du serveur valable jusqu'au {r['expires']} (à renouveler avant).")
    print(f"À distribuer : {r['paths']['ca.pem']}   |   à garder hors ligne : {r['paths']['ca.key']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
