"""Confiance TLS : on peut épingler l'autorité FPH (fichier ca.pem) au lieu de dépendre du magasin
du système. Sans ca_file : validation normale (magasin système). La vérification n'est JAMAIS désactivée."""
import os
import ssl


def make_verify(ca_file: str | None = None):
    ca_file = ca_file or os.environ.get("FPH_CA_CERT") or None
    if ca_file:
        if not os.path.isfile(ca_file):
            raise FileNotFoundError(f"Certificat de l'autorité FPH introuvable : {ca_file}")
        return ssl.create_default_context(cafile=ca_file)     # vérifie aussi le nom d'hôte
    return True
