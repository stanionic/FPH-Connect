# Base institutionnelle : responsables, organisations, événements

## Qui voit quoi (vérifié par tests)
| Donnée | National | Départemental | Admin d'église / d'organisation | Employé / chef de service | Public |
|---|---|---|---|---|---|
| Pasteurs et responsables (coordonnées) | tous | son département | son église / son organisation | **aucun** | **jamais** |
| Organisations | toutes | son département | la sienne | aucun | validées (à venir sur le site) |
| Événements | tous | son département | les siens | ceux de son église (lecture) | publiés seulement |
| Inscrits (nom, e-mail, téléphone) | tous | son département | ceux de ses événements | **aucun** | **jamais** |

Hors périmètre : réponse « introuvable » (on ne révèle pas l'existence). Les droits sont des permissions en
base (`leader:*`, `org:*`, `event:*`, `registration:manage`, `workflow:*`), modifiables sans changer le code.

## Minimisation des données personnelles
- Responsables : nom, fonction, rattachement, téléphone et e-mail **professionnels**, statut. Pas de date de naissance,
  pas de pièce d'identité, pas d'adresse personnelle.
- Les historiques et le journal d'audit n'enregistrent **jamais** noms, téléphones ni e-mails : seulement qui, quand,
  quel champ a changé. Consulter la fiche d'un responsable est journalisé.
- Inscrits : consentement obligatoire (horodaté). **Effacement** (`POST /api/v1/registrations/{id}/erase`) : les données
  sont anonymisées, la place est réattribuée à la liste d'attente.

## Règles métier
- Circuit de validation commun : brouillon → en attente → approuvé → publié → retiré / archivé. Toute modification d'une
  organisation ou d'un événement validé le **remet en attente** (et le retire du site).
- Événements : date avec fuseau horaire obligatoire ; fin ≥ début ; date limite ≤ début ; capacité optionnelle ; au-delà,
  **liste d'attente** avec promotion automatique à chaque annulation ou effacement.
- Responsables : un changement de fonction ou de rattachement clôt l'affectation en cours et en ouvre une nouvelle
  (historique des nominations).

## Reprise d'un registre externe (liste MEOL)
`python scripts/import_meols.py` lit un PDF du registre MEOL (Missions, Églises, Organisations,
Associations, Ligues de pasteurs) et l'écrit dans `organizations` + `leaders`/`leader_assignments`.
Trois garde-fous, choisis pour ne jamais faire apparaître une donnée que le registre ne donne pas :

- **une ligne importée reste `draft`** et `affiliation_status=pending` : rien n'est publié sans relecture ;
- **le département n'est pas inventé.** Déduit de l'adresse, sinon du nom, il reste « À déterminer » sinon.
  Comme ce n'est aucun des dix départements, la fiche n'est visible d'aucun responsable départemental :
  seul le niveau national la voit, en attente de relecture (`PATCH /api/v1/organizations/{id}` accepte
  `department` précisément pour permettre de trancher) ;
- **les téléphones et e-mails du registre sont ceux de l'organisme**, pas d'une personne : ils restent sur
  l'organisation et nulle coordonnée n'est attribuée à un responsable.

Le compte annoncé en dernière page du PDF sert de contrôle : s'il ne correspond pas aux entrées lues,
l'import refuse de démarrer. Toute décision prise sur une frontière de page (entrée coupée entre deux
pages) est consignée, et les déductions sont regroupées dans un rapport de relecture
(`--review docs/MEOL_A_VERIFIER.md`). L'import est idempotent : le relancer ne duplique rien.

## Pas encore fait
Documents justificatifs des organisations, rapports et documents liés aux événements, annonces, publication des
organisations sur le site, e-mails de confirmation d'inscription, export CSV des inscrits, portail d'administration graphique.
Le client Kivy n'a pas d'écran « organisations » : la relecture d'une fiche importée se fait donc pour l'instant
par l'API (ou en SQL), pas depuis l'interface.
