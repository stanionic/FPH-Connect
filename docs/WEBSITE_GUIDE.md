# Guide de connexion du site web

## 0. Principe de sécurité
Publication progressive : intégration créée **désactivée** et en **mode test** ; rien n'est envoyé
tant que vous n'avez pas passé `mode=live`. Le contenu WordPress existant n'est jamais modifié :
le plugin ajoute un type séparé `fph_church`.

## 1. Site WordPress actuel (transition)
1. **Sauvegardez** la base et `wp-content` (hébergeur ou plugin de sauvegarde).
2. Copiez `connectors/wordpress/fph-connect/` dans `wp-content/plugins/`, **sur un site de test
   d'abord**, et activez-le.
3. Créez l'intégration (admin national) : `POST /api/v1/admin/integrations`
   `{"name":"wp-prod","kind":"wordpress","base_url":"https://votre-site.org"}` → notez le `secret`.
4. Ajoutez dans `wp-config.php` : `define('FPH_SYNC_SECRET','<secret>');`
5. `PATCH …/{id}` `{"enabled":true}` (mode test), puis `POST …/{id}/resync` et `POST …/dispatch`.
   Vérifiez dans `GET …/{id}/outbox` le contenu `dry_run`.
6. Passez `{"mode":"live"}`, `resync`, `dispatch`. Le worker (`python -m app.worker`) assure ensuite l'envoi.
7. Page : ajoutez le shortcode `[fph_churches]`.

## 2. Futur site Flask
    pip install ./connectors/flask
    store = SqliteStore("fph_site.db")
    app.register_blueprint(create_blueprint(os.environ["FPH_SYNC_SECRET"], store))
    # vues : store.list_churches(department="Ouest")
Créez une intégration `kind="flask"`. Le récepteur utilise sa propre table ; vos modèles restent à vous.
Pour la migration WordPress → Flask : créez la 2ᵉ intégration en mode test, `resync`, vérifiez,
puis `live` ; désactivez ensuite l'intégration WordPress.

## 3. Retour arrière et incidents
- `POST …/{id}/rollback` : le site retire tout ce que FPH y a publié (brouillons sous WordPress).
- `POST …/{id}/resync` : republie.
- `GET …/{id}/export` : sauvegarde JSON de l'état publié.
- Interrupteur d'urgence côté site : `FPH_SYNC_DISABLED` (WordPress) ou paramètre `enabled` (Flask).
- Désactiver l'intégration (`enabled=false`) n'arrête rien d'autre dans la plateforme.
- Élément `dead` : corrigez la cause, puis `POST …/outbox/{seq}/requeue`.
- Secret compromis : `POST …/{id}/rotate-secret`, puis mettez à jour le site.


## 4. Événements et inscriptions (v0.4)
- Les événements **publiés** partent vers le site comme les églises (même file, mêmes reprises, même retour arrière).
  Modifier un événement publié le **retire du site** jusqu'à nouvelle validation ; **ouvrir/fermer les inscriptions**
  (`POST /api/v1/events/{id}/registration`) ne le retire pas : la fermeture rapide est possible.
- **WordPress** : ajouter dans `wp-config.php` `FPH_API_URL` et `FPH_INTEGRATION_ID` (en plus de `FPH_SYNC_SECRET`).
  Shortcodes : `[fph_events]` (liste) et `[fph_event_registration]` (formulaire, sur la page d'un événement).
  Le plugin transmet l'inscription **depuis le serveur WordPress**, signée ; il contient un anti-robot (champ piège +
  jeton `nonce`). **Non testé dans WordPress.**
- **Flask** : `forward_registration(base_url, integration_id, secret, payload, idempotency_key=...)` signe et envoie
  (voir `connectors/flask`). Appelez-la depuis votre vue de formulaire, jamais depuis du JavaScript navigateur.
  Ajoutez votre propre anti-spam (CAPTCHA) : la limite de 60 requêtes/minute protège le serveur, pas votre formulaire.
- Consulter les inscrits : `GET /api/v1/events/{id}/registrations` (responsables autorisés de l'événement uniquement).

## 5. Application web installable (PWA)
L'application Flask de `pwa/` fournit un annuaire public des églises affiliées, les événements publiés
et une connexion à l'API FPH. Elle peut être lancée avec `docker compose up -d pwa` (ou
`cd pwa && pip install -r requirements.txt && FPH_API_URL=http://127.0.0.1:8000 python app.py`).
La PWA est disponible sur `http://127.0.0.1:5000` en développement. En production, publiez-la
derrière HTTPS avec l'API et configurez `FPH_API_URL` comme URL API joignable depuis le conteneur.
La connexion utilise un proxy Flask de même origine ; aucun jeton n'est enregistré dans le stockage
du navigateur, et il faut se reconnecter après un rechargement. Le service worker met en cache
uniquement l'interface et ses ressources, jamais l'API ni les données personnelles.
