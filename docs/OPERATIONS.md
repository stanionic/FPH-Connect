# Exploitation : comptes administrateurs

## Créer le premier super administrateur
- **Installation neuve** : variables `FPH_BOOTSTRAP_ADMIN_USERNAME` (ex. `Admin`) et `FPH_BOOTSTRAP_ADMIN_PASSWORD` dans `.env`. Le compte n'est
  créé **qu'une fois, si la base est vide**. Il devra changer son mot de passe à la première connexion.
- **Base déjà utilisée** (le compte existe, ou il faut un compte de secours) : outil d'exploitation, à lancer **sur le serveur** :

      python -m app.admin_cli create-superadmin --username Admin
      python -m app.admin_cli reset-password    --user Admin
      python -m app.admin_cli rename            --user FPH-2026 --to Admin
      python -m app.admin_cli unlock            --user Admin

  Sous Docker : `docker compose exec server python -m app.admin_cli reset-password --user Admin`.

## Règles de l'outil
- **Aucune option `--password`** : un mot de passe en argument reste dans l'historique du terminal et dans la liste des processus. L'outil
  le **demande au clavier** (deux fois). `FPH_NEW_PASSWORD` existe pour l'automatisation, mais le taper devant la commande l'écrit dans
  l'historique : préférer la saisie.
- Politique : 10 caractères minimum, lettres **et** chiffres/symboles.
- `reset-password` **ferme immédiatement toutes les sessions** ouvertes du compte et le déverrouille. Le compte doit changer son mot de passe
  à la connexion suivante (`--keep` pour l'éviter).
- Chaque action est inscrite dans le journal d'audit (qui, quoi, quand), **sans jamais écrire de mot de passe**.
- L'accès au shell du serveur vaut confiance totale : protéger cet accès (SSH par clé, comptes nominatifs).

## Bonnes pratiques et risques connus
- Un pseudo comme `Admin` et un mot de passe bâti sur le nom de l'organisation et l'année sont **les premières choses qu'un attaquant essaie**.
  Après le changement obligatoire, choisir une phrase de passe **longue et unique** (jamais réutilisée ailleurs). Un mot de passe qui a été écrit dans un
  message, un e-mail ou un document est à considérer comme **compromis**.
- Protection contre les essais répétés : 5 échecs = compte verrouillé 15 minutes. **Effet de bord** : quelqu'un peut verrouiller volontairement
  le compte `Admin` en boucle. Remède : `unlock` ; mesure préventive : un pseudo moins évident pour le super administrateur, et des comptes
  nominatifs pour le travail quotidien (le super administrateur sert à l'administration).
- **Pas d'authentification à deux facteurs** (non implémentée) : le TLS et un mot de passe solide sont la seule protection du compte.
- Ne jamais mettre un mot de passe dans un fichier versionné, un ticket ou une conversation ; `.env` doit rester privé (droits 600).
