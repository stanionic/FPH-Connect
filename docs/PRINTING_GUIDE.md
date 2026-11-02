# Guide de l'impression réseau

## Principe
Un employé ouvre un PDF sur son poste, choisit une imprimante FPH située dans un autre bureau, et le document
passe par le **serveur FPH** puis par un **agent d'impression** installé sur le poste qui héberge l'imprimante.
```
Poste utilisateur ──► Serveur FPH (file, droits, journal) ◄── Agent (poste du bureau) ──► Imprimante (USB / réseau / CUPS / Windows)
```
- **Aucune imprimante n'est jamais exposée** : seul l'agent ouvre une connexion (sortante) vers le serveur. Aucun
  utilisateur ne parle directement à une imprimante ni à l'agent.
- **Rien n'est partagé par défaut.** L'agent n'annonce que les files de sa liste explicite (`FPH_AGENT_SHARE`).
  Une imprimante annoncée est créée **désactivée** ; un administrateur doit l'**activer**, puis **accorder l'accès**
  à chaque utilisateur (ou l'ouvrir à tout le personnel). Refus par défaut. Le poste de l'utilisateur doit aussi être approuvé.

## Mise en route
1. **Administrateur** : `POST /api/v1/admin/agents {"name","platform"}` → récupérer `device_header` (**affiché une seule fois**).
2. **Poste du bureau** (celui où l'imprimante est installée/partagée) :
   `pip install -r agent/requirements.txt`, puis
   `FPH_URL=… FPH_AGENT_TOKEN=<device_header> FPH_AGENT_SHARE="HP-LaserJet" FPH_AGENT_BACKEND=cups python -m fph_agent`
   (exemple de service : `agent/fph-agent.service.example`, non testé).
3. **Administrateur** : `GET /api/v1/admin/printers` → `PATCH …/{id} {"enabled":true,"location":"Bureau 2"}` →
   `PUT …/{id}/grants/{user_id}`. Retrait : `DELETE …/grants/{user_id}` ; agent compromis : `POST /api/v1/devices/{id}/revoke`.
4. **Utilisateur** : écran « Imprimer » de l'application (ou `POST /api/v1/print-jobs`).

## États d'un travail (uniquement ce qui est réellement connu)
| État | Signification |
|---|---|
| en attente | reçu par le serveur, aucun agent ne l'a encore pris |
| accepté | pris par l'agent et transmis à la file locale |
| en cours | la file locale indique qu'il s'imprime |
| **terminé** | la file locale **confirme** la fin |
| **transmis (fin non confirmable)** | envoyé à la file mais impossible de savoir s'il est sorti (Windows, ou travail introuvable) |
| erreur | refusé, expiré (24 h hors ligne), fichier corrompu, etc. |
| annulé | annulé avant impression |

**Annulation** : en attente = immédiate. Déjà pris en charge = *demandée* à l'agent ; si le papier est déjà sorti, le
travail finit « terminé » (jamais un faux « annulé »). Propriétaire ou administrateur d'impression.

## Options et formats
Copies (1 à `max_copies`), recto/recto-verso, couleur, papier : refusés si l'imprimante ne les déclare pas.
**Formats : PDF, PNG, JPEG, texte.** Word/Excel : convertir en PDF d'abord. Limite 20 Mo.
**Les capacités sont déclarées en configuration** (`FPH_AGENT_CAPS`, fichier JSON), pas détectées. Par défaut :
recto seul, **pas de couleur**, papier A4/Letter, 10 copies. Exemple : `{"HP-LaserJet": {"duplex": true, "color": true}}`.

## Confidentialité
Le document est **supprimé du serveur dès l'état final** et du poste de l'agent dès l'envoi à la file locale.
Le nom du fichier est conservé dans l'historique (visible du propriétaire et des administrateurs d'impression) mais
**jamais** dans le journal d'audit. Plafond : 20 travaux actifs par utilisateur.

## Limites réelles — à lire
- **Jamais testé** avec un vrai CUPS, une vraie imprimante, Windows, ni Android. Le backend CUPS a été vérifié contre de
  **faux** exécutables `lp`/`lpstat`/`cancel` qui imitent le format documenté : cela ne prouve pas la compatibilité.
- **Backend Windows** (SumatraPDF) : jamais exécuté ; **la fin d'impression n'est pas suivie** (« transmis »).
- **Impression en double possible** dans un cas rare : l'agent soumet à la file puis disparaît *avant* de confirmer à
  temps ; après 5 minutes le travail est repris (3 essais max). Une fois l'envoi confirmé, aucune reprise n'a lieu (testé).
- **Pas d'intégration au système** : l'imprimante n'est **pas** ajoutée dans les paramètres Windows/Linux/Android ;
  l'impression passe par l'écran « Imprimer » de l'application. Pas de pilote d'impression virtuel ni d'impression IPP directe.
- **Android** : pas d'intégration au service d'impression du système ; l'écran Kivy utilise la même API (non lancé).
- **Les documents circulent en clair** sur le réseau local **sauf si le TLS est activé** (`docs/TLS_GUIDE.md`, fourni et testé en boucle locale ; l'agent s'y connecte avec `FPH_CA_CERT`). Le serveur, lui, voit le document en clair.
- Sites distants : VPN à mettre en place (non fourni). Pas de quotas de pages, pas de facturation, pas de tâche de purge de l'historique.
