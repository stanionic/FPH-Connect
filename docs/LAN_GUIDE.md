# Guide du réseau local FPH (machines, utilisateurs, messages)

## Principe
Toutes les communications passent par **le serveur FPH du réseau local** (pas de pair-à-pair).
Une communication exige **deux autorisations** : un **utilisateur** actif ET une **machine approuvée**
par un administrateur (super administrateur ou administrateur national). Être découverte sur le
réseau ne donne **aucun droit**.
Si le serveur est arrêté, plus personne ne communique ; en attendant, les clients conservent
localement leurs messages et documents et les envoient une seule fois au retour du serveur.

## Mise en route (super administrateur)
1. `cp .env.example .env`, renseigner `FPH_SECRET_KEY`, `POSTGRES_PASSWORD` et
   `FPH_BOOTSTRAP_ADMIN_PASSWORD`. Ne jamais partager ni versionner `.env`.
2. `docker compose --profile local up -d` (serveur, base, envoi, annonce réseau).
3. Première connexion avec le pseudo défini dans `FPH_BOOTSTRAP_ADMIN_USERNAME` (ex. `Admin`) : **le changement de mot de passe est obligatoire**
   (toute autre action est refusée tant qu'il n'est pas fait). Un mot de passe qui a été écrit dans
   un message ou un document doit être considéré comme compromis : le changer.
4. Créer les utilisateurs (`POST /api/v1/users`) avec leur rôle, leur église ou département.
5. Sur chaque machine : l'application propose « Enregistrer cet appareil » → l'appareil est
   **en attente**. L'administrateur l'approuve (`POST /api/v1/devices/{id}/approve`, avec le bureau,
   et au besoin un utilisateur attribué) ; il peut le révoquer à tout instant (`/revoke`, effet immédiat).
6. Vérification : `python scripts/lan_smoke_test.py` (voir l'en-tête du script ; écrit des données de test).

## Ce que les machines autorisées peuvent faire
Présence (qui est en ligne, mise à jour toutes les ~30 s), annuaire des utilisateurs autorisés,
messages directs, diffusion générale (réservée aux administrateurs nationaux), dépôt de documents.
Les droits par rôle se modifient dans la table `roles` (permissions `message:*`, `device:*`, `document:*`).

## Réseau
| Port | Usage |
|---|---|
| 8000/tcp | API (derrière un proxy TLS en production) |
| 50505/udp | découverte du serveur (broadcast) |

Pare-feu : n'ouvrir ces ports qu'au réseau interne. **La découverte ne traverse ni routeur ni VLAN**
et est bloquée par l'« isolation des clients » de certains Wi-Fi : saisir alors l'URL du serveur à la main.
Donner une **adresse IP fixe** au serveur.

## Sécurité à connaître
- **Chiffrement (TLS)** : fourni et testé (voir `docs/TLS_GUIDE.md`). Sans lui, mots de passe, messages et documents circulent
  lisibles sur le réseau. En production, le serveur **refuse de démarrer sans TLS**. Les postes font confiance à l'autorité FPH
  (`FPH_CA_CERT`) : un faux serveur est refusé. Jamais testé entre plusieurs machines réelles.
- Les messages ne sont pas chiffrés de bout en bout : ils sont lisibles dans la base par ses administrateurs.
  Le contenu n'est pas écrit dans le journal d'audit (seulement qui, quand, et le type).
- Le jeton de l'appareil est un secret conservé dans un fichier local (droits 0600) ; un appareil volé
  se révoque côté serveur.
