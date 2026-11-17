# Guide des documents : zone tampon → classement en un clic

## Fonctionnement
1. Un utilisateur autorisé (sur une machine approuvée) **partage** un document : il est écrit sur le
   disque du serveur dans une **zone tampon** (pas dans la mémoire vive, pour survivre à une coupure
   de courant) avec son empreinte SHA-256. Hors ligne, le client le garde dans un dossier tampon local.
2. Un administrateur (national ou départemental) clique sur **« Classer en un clic »**
   (`POST /api/v1/documents/inbox/organize`). Chaque fichier est traité séparément :
   - **classé** : type et église reconnus → fiche en base + fichier rangé par type/église/année ;
   - **déjà présent** (même empreinte) : pas de doublon ;
   - **à vérifier** : au moindre doute, il reste en tampon avec la raison (jamais rangé au hasard) ;
   - **erreur** : un fichier manquant ou illisible n'arrête pas les autres.
3. Le lot est **annulable** (`/inbox/batches/{lot}/undo`) : les documents retournent dans la zone tampon.
4. Les éléments « à vérifier » se classent à la main (`/inbox/{id}/file`) ou en relançant le clic avec
   `{"include_review": true}` (utile au niveau national, qui voit plus d'églises).

## Règles de classement (simples et explicables)
Type : mots-clés du **nom du fichier** (procès-verbal/PV, lettre, rapport, certificat, affiliation,
en français, créole et anglais) ; sinon début du contenu pour `.txt` et `.docx`. Deux types possibles = « à vérifier ».
Église : son nom officiel complet doit apparaître dans le nom ou le début du contenu ; deux églises
possibles = « à vérifier ». Certificats et documents d'affiliation exigent une église.
L'expéditeur peut aussi **indiquer** le type et l'église, ce qui prime.
Un responsable départemental ne classe que dans son département ; le classement « national »
(sans église) est réservé aux administrateurs nationaux.

## Partage direct au réseau FPH (PWA)
En plus de la zone tampon, un utilisateur autorisé peut **partager directement** un fichier avec un
**court message** (500 caractères maximum) depuis la page `/partage` du PWA :

- `POST /api/v1/documents/share` (multipart : `file`, `title`, `message`) ;
- le fichier est marqué `visibility = network` : tout compte disposant de `document:read` peut le voir
  et le télécharger, quel que soit son département ou son église ;
- l'auteur (ou le SuperAdmin) peut le retirer du partage (`DELETE /api/v1/documents/{id}`) ;
- chaque partage et retrait est journalisé (`document.shared`, `document.unshared`).

Le partage ne dépend pas d'un appareil approuvé, contrairement à la zone tampon : il fonctionne donc
depuis un simple navigateur. La taille maximale suit `FPH_MAX_UPLOAD_MB` (20 Mo par défaut).

### Autorisations accordées par le SuperAdmin
Les droits `document:share`, `document:read`, `document:organize` et `print:use` peuvent être accordés
**nommément** à n'importe quel compte, en plus des droits de son rôle :

- `GET /api/v1/users/permissions/catalog` : catalogue des droits accordables ;
- `PUT /api/v1/users/{id}/permissions` : remplace les droits nominaux (SuperAdmin uniquement) ;
- `PATCH /api/v1/users/{id}` accepte aussi `extra_permissions` ;
- la réponse utilisateur expose `permissions` (effectives) et `extra_permissions` (nominaux).

Dans la console `/admin`, ces cases se trouvent dans le formulaire utilisateur
(« Autorisations supplémentaires ») ; le client Kivy propose les mêmes cases.

## Limites réelles
- **Les PDF ne sont pas lus** (pas d'extraction de texte, pas d'OCR) : leur classement repose sur le nom du fichier.
  Un scan nommé `scan001.pdf` ira en « à vérifier ».
- Aucun **antivirus** : seuls l'extension, la signature du fichier et la taille (20 Mo) sont contrôlées.
  Types acceptés : pdf, doc, docx, odt, xlsx, png, jpg, txt.
- Pas de versions d'un même document : un fichier modifié est un nouveau document.
- **Sauvegarde** : sauvegarder ENSEMBLE la base et le dossier de stockage (`FPH_STORAGE_DIR`), sinon la
  restauration sera incohérente. Sauvegarde automatique non implémentée.
