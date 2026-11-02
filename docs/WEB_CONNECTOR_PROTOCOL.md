# Protocole FPH → site web (v1)

Le serveur FPH **pousse** les changements ; le site ne contacte jamais la base FPH.
Un seul protocole pour WordPress (transition) et Flask (futur site) : changer de site ne change
rien côté serveur ni côté application mobile.

`POST {base_url}/fph-sync` (WordPress : `/wp-json/fph/v1/sync`)

| En-tête | Rôle |
|---|---|
| `X-FPH-Timestamp` | secondes UNIX ; refusé si l'écart dépasse 300 s |
| `X-FPH-Signature` | `sha256=` + HMAC-SHA256(secret, `timestamp + "." + corps brut`) |
| `X-FPH-Event-Id` | `integration_id:seq`, pour le diagnostic |

Corps : `{"seq":int,"action":"upsert|remove","kind":"church|event","entity_id":"…","data":{…}|null}`
(+ `church_id` ou `event_id` selon le type, pour les récepteurs v1). `kind` absent = `church`.
`data` = champs publics uniquement.
- `church` : nom, adresse, département, commune, coordonnées, téléphone.
- `event` : titre, description, début, fin, lieu, département, inscriptions ouvertes, date limite.
  Jamais d'inscrit, jamais d'identifiant d'utilisateur. Le numéro `seq` est ordonné **par entité**.

Règles du récepteur : signature invalide → 401 ; charge invalide → 422 ; `seq` ≤ dernier `seq`
connu pour cette église → 200 `ignored_stale` (rejeu et désordre sans effet) ; `remove` masque
(réversible), ne supprime jamais. Répondre 2xx = « traité ou ignoré ».

Côté serveur : 5xx, 408, 429, 401/403 et erreurs réseau → nouvelle tentative (1 min, 5 min, 30 min,
2 h, 12 h), puis état `dead` après 6 essais (relançable). 400/404/405/410/413/422 → `dead` aussitôt.
Les modifications successives d'une même fiche en attente sont fusionnées (`superseded`).

Le secret est dérivé de `FPH_SECRET_KEY` : il n'est pas stocké en base, il est affiché une seule
fois à la création ou à la rotation.


## Sens inverse : inscriptions envoyées par le site (v1)

`POST {FPH}/api/v1/inbound/{integration_id}/registrations`, appelé par **le serveur du site**
(WordPress côté PHP, Flask côté Python), **jamais par le navigateur du public** : le secret ne doit
pas sortir du serveur.

| En-tête | Rôle |
|---|---|
| `X-FPH-Timestamp` / `X-FPH-Signature` | identiques au sens FPH → site (HMAC du corps brut, ±300 s) |
| `X-FPH-Idempotency-Key` | **obligatoire**, 8 à 100 caractères, UNE par envoi de formulaire, réutilisée en cas de nouvel essai |

Corps : `{"event_id","full_name","email"?,"phone"?,"consent":true}` (e-mail ou téléphone requis,
consentement obligatoire). Réponses : `200 {"status":"registered|waitlisted","registration_id"}` ;
même clé rejouée ou même personne = même inscription, sans doublon ; `409 registration_closed` ;
`404` (intégration inconnue/désactivée, événement non publié) ; `401` signature ; `422` données ;
`429` plus de 60 requêtes/minute par intégration (compteur par processus). En mode `test` :
`200 {"status":"dry_run"}`, rien n'est enregistré.
