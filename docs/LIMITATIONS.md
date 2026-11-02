# État réel et limites connues (v0.9)

## Testé automatiquement (137 tests, SQLite)
- Tout ce qui précède (v0.4) : comptes, églises, responsables, organisations, événements, inscriptions, site (Flask),
  réseau local, messages, documents.
- **Impression — serveur** : refus par défaut (découverte ≠ autorisation), accès par utilisateur ou ouvert au personnel,
  options validées contre les capacités, formats imprimables, idempotence, plafond de travaux, cycle de vie complet,
  document supprimé à l'état final, isolation entre agents et entre utilisateurs, annulation (propriétaire/administrateur),
  reprise après panne de l'agent **sans double impression une fois l'envoi confirmé**, expiration, états « transmis »
  (jamais un faux « terminé »), agent révoqué, journal d'audit sans noms de documents.
- **Impression — agent** : de bout en bout contre le serveur avec une imprimante virtuelle « fichier » ; partage limité à la
  liste explicite ; contrôle local ; fichier corrompu détecté ; panne du backend ; redémarrage sans mémoire ; annulation ;
  panne réseau sans perte ; aucun document résiduel ; commandes sans shell (aucune injection, titres/noms/options assainis).
- **Interface Kivy, pilotée comme un utilisateur** (`scripts/ui_check.py`, aussi dans pytest) : application **réelle** dans une fenêtre virtuelle de la
  taille d'un téléphone (360×640), contre un vrai serveur et un vrai agent d'impression ; **47 contrôles** sur connexion (message d'erreur, logo FPH affiché), églises,
  création d'église **hors ligne** puis synchronisation, réseau local (appareil → approbation → présence → messages), documents (envoi, classement en un
  clic), impression (autorisation, travail, « terminé »), événements (consentement, doublon, statistiques), registre MEOL (liste des fiches importées, contact,
  recherche, filtre par département, département sans fiche, retour), **changement de langue à chaud**, effacement du
  pseudo à la déconnexion. Des captures d'écran sont produites. Elles ont permis de **trouver et corriger** : boutons qui débordaient, ligne d'état coupée,
  codes anglais (`[draft]`, `[organized]`) affichés, champ « Copies » sans étiquette, **langue impossible à changer** (aucun sélecteur et aucune mise à jour à l'écran).
- **Exécutables Linux** (`scripts/build_executables.py`) : client et agent **construits avec PyInstaller puis démarrés** en mode auto-test (aussi
  depuis un autre dossier, environnement vide) ; l'auto-test est lui-même vérifié capable d'**échouer** (traduction cassée volontairement).
  Détail et limites : `docs/BUILD_GUIDE.md`.
- **Outil d'exploitation des comptes** (`python -m app.admin_cli`) : création, renommage, réinitialisation (sessions coupées aussitôt), déverrouillage, mot
  de passe jamais accepté en argument, audit sans mot de passe ; démontré aussi sur un vrai serveur (installation neuve et déploiement existant).
- **Chiffrement TLS** : certificats bien formés (autorité, SAN, usage, signature, clés en 0600), renouvellement sans changer l'autorité,
  entrées invalides refusées, **vraies poignées de main** (autorité inconnue, mauvais nom d'hôte et HTTP clair refusés), client / agent /
  outil du site, refus de démarrer en production sans TLS, avertissement si le proxy peut être contourné.
- Migrations 0001 à 0005 : montée depuis une base v0.4 avec données, retour arrière, installation neuve, `alembic check`.

## Vérifié sur un vrai serveur HTTP (boucle locale uniquement)
`scripts/lan_smoke_test.py` : **35 contrôles en HTTP, 38 en HTTPS** (certificat vérifié, découverte annonçant `https`) ; (découverte UDP, machines, messages, révocation, documents,
événement et inscription signée, **impression avec un vrai agent** : refus, options, impression, annulation, révocation).
**Ce n'est pas un test sur plusieurs machines** : aucun routeur, Wi-Fi, pare-feu ni second ordinateur réel.

## Écrit mais NON vérifié
- **Exécutable Windows (.exe)** et **APK Android** : jamais construits (le premier exige Windows, le second des SDK/NDK Android non téléchargeables
  ici). `client/buildozer.spec` n'a jamais été exécuté ; problèmes connus côté Android dans `docs/BUILD_GUIDE.md` (sélecteur de fichiers, certificat).
- **Backend CUPS** : testé uniquement contre de faux `lp`/`lpstat`/`cancel` ; **jamais** contre un vrai CUPS ni une vraie imprimante.
- **Backend Windows** (SumatraPDF) : seule la construction de la commande est testée (appel simulé) ; jamais exécuté sous Windows.
- **Plugin WordPress** : PHP absent, jamais exécuté, syntaxe non validée.
- **Interface Kivy sur Android, sous Windows, au toucher, avec un vrai clavier tactile** : jamais lancée ni essayée (seulement Linux, fenêtre virtuelle, rendu logiciel). La lisibilité réelle, la taille des zones à toucher et les polices ne sont pas évaluées.
- PostgreSQL, Docker Compose (montage des certificats compris), Buildozer/Android, service systemd d'exemple, proxy TLS (nginx/Caddy) : jamais lancés.
- **TLS entre plusieurs machines, sous Windows et sous Android** : jamais testé (seulement la boucle locale).

## Limites de conception
- **Traductions** : le créole haïtien et l'anglais sont des traductions de travail **à faire relire** par des locuteurs ; aucune validation externe.
- Impression : pas d'intégration au système (imprimante absente des paramètres Windows/Linux/Android), pas d'IPP direct,
  formats PDF/PNG/JPEG/texte seulement, capacités déclarées (non détectées), impression en double possible dans une fenêtre
  étroite (voir `docs/PRINTING_GUIDE.md`), fin d'impression non suivie sous Windows.
- Tout passe par le serveur local. **Le TLS existe mais doit être activé** (en développement le serveur démarre en HTTP clair avec
  un avertissement ; en production il refuse). Pas de révocation de certificat, pas de certificat client ; messages et documents
  restent lisibles par le serveur (pas de chiffrement de bout en bout).
- Découverte UDP : ne traverse pas routeurs/VLAN. Limitation de débit des inscriptions : par processus.
- Documents : PDF non lus, pas d'antivirus, pas de versions, sauvegarde automatique non implémentée.

## Non implémenté
Documents justificatifs des organisations et documents d'événements, annonces, publication des organisations sur le site,
MFA (authentification à deux facteurs), réinitialisation de mot de passe par e-mail (seul l'outil d'exploitation sur le serveur le permet), portail d'administration graphique, écrans Kivy pour les responsables, les organisations, la création et la validation des événements et l'administration
(seuls existent : églises, réseau, documents, impression, inscriptions aux événements), WebSocket, quotas de pages, purge de l'historique d'impression, sauvegardes automatiques et test de
restauration, installateurs (MSI, .deb), signature de code, mise à jour automatique, audit de sécurité externe.
