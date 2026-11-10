# FPH Connect — Architecture et décisions (v0.1)

```
Client Kivy (Android/Win/Linux) ──HTTPS──► FPH Core Server (FastAPI) ──► PostgreSQL
   │ SQLite local + file d'ops                │ audit, rôles, publication
   └ jamais d'accès direct à la base           └──► Web Connector (phase 3) ──► site FPH
                                              └──► Agents réseau (phase 4) ──► imprimantes
```

## Décisions
- **Serveur central unique** : seule source de vérité ; le site et les clients passent par l'API.
- **Statuts de publication** : draft → pending → approved → published → withdrawn / archived.
  Le public ne voit que `published` + `affiliated`, avec champs publics seulement.
  Toute modification d'une fiche la remet en `pending` (rien de non validé ne reste public).
- **Rôles en base** (table `roles`, permissions en JSON) : modifiables sans changer le code.
  Périmètre : national = tout ; départemental = son département ; église = sa propre église.
  Hors périmètre → 404 (n'indique pas l'existence).
- **Sessions révocables** : jeton JWT lié à une session en base ; désactivation d'un compte =
  révocation immédiate. Mots de passe : scrypt. Verrouillage après échecs répétés.
- **Concurrence** : champ `version` + 409 en cas de conflit ; clé `Idempotency-Key` contre les doublons.
- **Hors ligne** : cache SQLite + file d'opérations avec identifiant unique ; conflit = opération
  marquée `conflict`, valeur locale conservée, rien d'écrasé.

## Site web FPH
Aujourd'hui WordPress ; sera refait en Flask. Décision : **un seul protocole** de publication
(`docs/WEB_CONNECTOR_PROTOCOL.md`), poussé par le serveur via une outbox transactionnelle.
Deux récepteurs : plugin WordPress (transition) et module Flask (cible). La migration consiste à
ajouter une 2ᵉ intégration, la valider en mode test, la passer en live, puis désactiver l'ancienne.
Le site ne touche jamais la base FPH ; le serveur ne touche jamais la base du site.

## PWA et client Kivy
La PWA et le client Kivy utilisent la même API FastAPI et donc la même base centrale. Le cache SQLite
du client Kivy reste local à l'appareil : il n'est pas partagé directement avec le navigateur. Le
registre MEOL de la PWA passe par une route protégée de l'API ; les permissions et le périmètre du
compte sont vérifiés par le serveur, comme dans Kivy.

## Hébergement
Mode A (hébergé) : `docker-compose.yml` fourni (PostgreSQL + serveur), reverse proxy HTTPS à ajouter.
Mode B (serveur local) : même image sur un serveur du réseau interne ; synchronisation vers le
central **non implémentée**. Ports : 443 (proxy), 8000 interne, 5432 non exposé.

## Risques de sécurité principaux
Jeton non persisté côté client (re-connexion à chaque lancement) ; pas de MFA ; pas de limitation de
débit par IP ; données personnelles de pasteurs pas encore modélisées ; sauvegardes à configurer.

## Réseau local, appareils et documents (v0.3)
Le serveur local est le hub : utilisateur autorisé + machine approuvée = droit de communiquer.
Les machines s'identifient par un jeton (condensé SHA-256 en base, révocable). La découverte UDP
n'annonce que l'existence du serveur. Les documents passent par une zone tampon persistante sur disque
puis un classement par règles explicables ; le doute n'est jamais rangé automatiquement.

## Base institutionnelle et site (v0.4)
Entités : pasteurs/responsables (avec historique d'affectations), organisations, événements, inscriptions.
Circuit de validation partagé (`workflow.py`). La file d'envoi vers le site (`outbox`) porte un `kind`
(église ou événement) : un seul mécanisme de reprises, de mode test et de retour arrière. Sens inverse :
le serveur du site transmet les inscriptions au point d'entrée signé `/api/v1/inbound/...`.
Détails : `docs/INSTITUTIONAL_DATA.md`.

## Chiffrement du réseau local (v0.6)
Petite autorité FPH + certificat serveur (`scripts/make_lan_certs.py`). Les clients (application, agent, outil du site) **épinglent**
l'autorité (`FPH_CA_CERT`) : la vérification du certificat et du nom n'est jamais désactivée, un fichier d'autorité absent est une
erreur (pas de repli silencieux). Le lanceur `python -m app.serve` refuse la production sans TLS. Détails : `docs/TLS_GUIDE.md`.

## Impression réseau (v0.5)
Serveur = file, droits et journal ; **agent** = seul composant au contact de l'imprimante, connexions sortantes uniquement,
sans mémoire propre (le serveur lui redonne les travaux à reprendre/annuler). Refus par défaut, rien de partagé sans liste
explicite. États limités à ce qui est réellement connu (« terminé » seulement si la file locale le confirme). Détails :
`docs/PRINTING_GUIDE.md`.
