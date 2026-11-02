# Guide du chiffrement (TLS) du réseau local

## Pourquoi
Sans TLS, mots de passe, messages, inscriptions et **documents imprimés** circulent lisibles pour quiconque écoute
le réseau (Wi-Fi partagé, poste infecté, prise réseau libre). Avec TLS, ils sont chiffrés **et** le poste vérifie qu'il
parle bien au vrai serveur FPH (un faux serveur sur le réseau est refusé).

## En 4 étapes
1. **Générer** (sur une machine de confiance) :
   `pip install -r scripts/requirements.txt && python scripts/make_lan_certs.py --out certs --ip 192.168.1.10 --name fph-serveur.local`
   → `ca.pem` (public, à distribuer), `ca.key` (**privée : à garder hors ligne** après usage), `server.pem` + `server.key`.
   Noter l'**empreinte SHA-256** affichée ; la comparer sur chaque poste : `openssl x509 -in ca.pem -noout -fingerprint -sha256`.
2. **Démarrer le serveur** en HTTPS : variables `FPH_TLS_CERT=…/server.pem`, `FPH_TLS_KEY=…/server.key`, puis `python -m app.serve`
   (Docker : dossier `certs/` monté en lecture seule, voir `docker-compose.yml`). Définir aussi `FPH_API_SCHEME=https` pour que la
   découverte réseau annonce l'adresse en `https`.
3. **Faire confiance à l'autorité FPH** sur chaque client : `FPH_CA_CERT=/chemin/ca.pem`
   (application, agent d'impression `python -m fph_agent`, script de vérification, et `ca_file=` dans `forward_registration` côté site Flask).
   C'est une confiance **épinglée** : seule l'autorité FPH est acceptée pour ce serveur, sans modifier le magasin du système.
4. **Vérifier** : `FPH_CA_CERT=… python scripts/lan_smoke_test.py` (contrôle aussi qu'un client SANS l'autorité est refusé).

## Production
Le serveur **refuse de démarrer** avec `FPH_ENV=prod` sans TLS. Seule exception : un proxy TLS placé devant (nginx, Caddy…) et déclaré
par `FPH_BEHIND_TLS_PROXY=1` ; le serveur doit alors n'écouter qu'en local (`FPH_HOST=127.0.0.1`, ou port Docker publié sur
`127.0.0.1`), sinon il peut être joint en clair en contournant le proxy (le lanceur avertit). Le proxy n'est ni fourni ni testé.

## Renouvellement et incidents
- Le certificat serveur dure au plus **825 jours** (date affichée à la génération) : relancer la même commande dans le même
  dossier le renouvelle **sans changer `ca.pem`** (aucun poste à reconfigurer), puis redémarrer le serveur.
- **L'adresse IP du serveur change** : refaire un certificat avec la nouvelle IP (le certificat n'est valable que pour les noms/IP indiqués).
- **`ca.key` perdue ou volée** : `--force` crée une nouvelle autorité ; **tous** les postes doivent recevoir le nouveau `ca.pem`.
- **L'horloge des postes doit être juste** : un certificat est refusé si la date du poste est fausse (fréquent sans serveur de temps).

## Limites réelles
- **Testé uniquement en boucle locale** (127.0.0.1) : poignées de main chiffrées réelles, refus d'une autorité inconnue, d'un mauvais
  nom d'hôte et du HTTP clair, 38 contrôles de bout en bout. **Jamais entre plusieurs machines**, ni sous Windows/Android.
- Pas de **révocation** de certificat (ni CRL, ni OCSP) : un certificat serveur compromis ne s'invalide qu'en changeant d'autorité.
- Pas de certificat **client** : les postes et agents s'authentifient par jeton, pas par certificat.
- TLS protège le **transport**. Le serveur voit toujours les messages et documents en clair (pas de chiffrement de bout en bout).
- La découverte UDP n'est **pas authentifiée** : un faux répondeur peut annoncer une fausse adresse. Un faux serveur ne peut pas
  présenter de certificat signé par l'autorité FPH, donc les clients configurés avec `FPH_CA_CERT` le refusent.
- **Android** : fournir le fichier `ca.pem` à l'application (variable `FPH_CA_CERT` non disponible telle quelle sur téléphone) — non testé.
