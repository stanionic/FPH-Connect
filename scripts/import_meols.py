#!/usr/bin/env python3
"""Listes MEOL de la FPH (Missions / Églises / Organisations / Associations / Ligues de pasteurs) :
comparaison des registres puis import dans la base de l'application.

    python scripts/import_meols.py parse    <nouveau.pdf>
    python scripts/import_meols.py compare  <ancien.pdf> <nouveau.pdf> [--out docs/MEOL_COMPARE.md]
    python scripts/import_meols.py import   <nouveau.pdf> [--as Admin] [--dry-run]
    python scripts/import_meols.py import   <nouveau.pdf> --api https://fph-serveur.local:8000 --user Admin

Deux chemins d'écriture, selon qui tient la base :
- `--db` (défaut) écrit via les modèles du serveur : administration d'une base joignable depuis la
  machine de l'opérateur (SQLite, ou Postgres exposé) ;
- `--api` enrole **auprès du serveur qui tourne** (`POST`/`PATCH /api/v1/organizations`) : c'est le seul
  chemin quand la base vit dans un conteneur sans port publié, et celui qui applique droits, versionnage,
  historique et audit au moment de l'écriture. Le mot de passe vient de `FPH_API_PASSWORD`, sinon il est
  demandé au clavier — jamais en argument. Les deux chemins sont rejouables : relancer n'ajoute rien
  aux fiches déjà entrées, ce qui permet d'enroler au fil de l'eau.

Prérequis : `pip install pypdf` (et `httpx` pour `--api`), voir scripts/requirements.txt. L'import se
sert des modèles du serveur (`server/app`), donc les règles du projet s'appliquent : une ligne importée
reste `draft` (jamais publiée automatiquement), le contact d'un responsable n'est que professionnel, et
chaque écriture laisse une trace dans `entity_history` et `audit_log`.

Le PDF est lu en mode « mise en page » : les colonnes sont séparées par plusieurs espaces, une
ligne vide sépare deux entrées, et une entrée coupée par un saut de page est raccordée à la
précédente quand un signe objectif le prouve (colonne « nom » vide, nom qui remonte dans l'ordre
alphabétique du registre, ou e-mail recoupé entre les deux pages). Le compte annoncé en dernière page
sert de contrôle : s'il ne correspond pas au nombre d'entrées lues, l'outil échoue au lieu d'importer
silencieusement du vide. Chaque décision prise sur une frontière de page est conservée (`parse
--boundaries`) : le doute est montré, jamais avalé.

Trois déductions sont assumées et donc visibles dans la liste à vérifier :
- le département est déduit de l'adresse, sinon du nom ; jamais inventé, il reste « À déterminer »
  quand rien ne le désigne. Cette valeur n'appartient à aucun responsable départemental : la ligne
  n'est alors visible qu'au niveau national, en attente de relecture ;
- le registre ne hiérarchise pas les responsables : le premier nommé est tenu pour principal ;
- téléphones et e-mails du registre sont ceux de l'organisme, pas d'une personne : ils restent sur
  l'organisation et ne sont attribués à aucun responsable.
"""
import argparse
import bisect
import getpass
import os
import re
import sys
import unicodedata
from collections import Counter
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_DB = f"sqlite:///{os.path.join(ROOT, 'server', 'fph_dev.db')}"
# Tout ce rapport est en français : sur une console Windows en cp437, un simple « — » ferait planter
# l'outil après avoir travaillé. La sortie est donc forcée en UTF-8.
for _flux in (sys.stdout, sys.stderr):
    if hasattr(_flux, "reconfigure"):
        _flux.reconfigure(encoding="utf-8", errors="replace")

COLS = ("name", "people", "phones", "emails", "address")
GAP = re.compile(r"\S(?:[^ ]| {1,2}\S)*")     # un segment = du texte jusqu'à 3 espaces ou plus
EMPTY_MARKS = {"", "-", "—", "–", "--"}

# (mot-clé trouvé dans l'adresse ou le nom, département, commune affichée) — ordre sans importance,
# mais les variantes accentuées ET non accentuées sont nécessaires (le PDF mélange les deux).
GEOGRAPHY = [
    ("port-au-prince", "Ouest", "Port-au-Prince"), ("port the prince", "Ouest", "Port-au-Prince"),
    ("delmas", "Ouest", "Delmas"), ("bas-delmas", "Ouest", "Delmas"), ("pétion-ville", "Ouest", "Pétion-Ville"),
    ("petition-ville", "Ouest", "Pétion-Ville"), ("croix-des-bouquets", "Ouest", "Croix-des-Bouquets"),
    ("croix des bouquets", "Ouest", "Croix-des-Bouquets"), ("cx-des-", "Ouest", "Croix-des-Bouquets"),
    ("carrefour", "Ouest", "Carrefour"), ("tabarre", "Ouest", "Tabarre"), ("cité soleil", "Ouest", "Cité-Soleil"),
    ("cite soleil", "Ouest", "Cité-Soleil"), ("gressier", "Ouest", "Gressier"), ("kenscoff", "Ouest", "Kenscoff"),
    ("léogâne", "Ouest", "Léogâne"), ("leogane", "Ouest", "Léogâne"), ("grand-goâve", "Ouest", "Grand-Goâve"),
    ("grand goave", "Ouest", "Grand-Goâve"), ("petit-goâve", "Ouest", "Petit-Goâve"),
    ("petit goave", "Ouest", "Petit-Goâve"), ("arcahaie", "Ouest", "Arcahaie"), ("l'arcahaye", "Ouest", "Arcahaie"),
    ("cabaret", "Ouest", "Cabaret"), ("thomazeau", "Ouest", "Thomazeau"), ("gauthier", "Ouest", "Gauthier"),
    ("turgeau", "Ouest", "Turgeau"), ("pernier", "Ouest", "Pernier"), ("pelerin", "Ouest", "Pèlerin"),
    ("canapé-vert", "Ouest", "Canapé-Vert"), ("martissant", "Ouest", "Martissant"),
    ("saint-maurice", "Ouest", "Saint-Maurice"), ("prestige", "Ouest", "Prestige"),
    ("bel-air", "Ouest", "Bel-Air"), ("dormy", "Ouest", "Dormy"), ("jérémie", "Grand'Anse", "Jérémie"),
    # Grand'Anse avant Sud : « Jérémie » sinon écrasé par des clés plus courtes
    ("anse-d'hainey", "Grand'Anse", "Anse-d'Hainey"), ("abracots", "Grand'Anse", "Abricots"),
    ("dame-marie", "Grand'Anse", "Dame-Marie"), ("roseaux", "Grand'Anse", "Roseaux"),
    ("beaumont", "Grand'Anse", "Beaumont"), ("maniche", "Grand'Anse", "Maniche"),
    ("sangha", "Grand'Anse", "Sangha"), ("moron", "Grand'Anse", "Moron"),
    ("chambellan", "Grand'Anse", "Chambellan"), ("robert-long", "Grand'Anse", "Robert-Long"),
    ("port-à-piment", "Grand'Anse", "Port-à-Piment"),
    ("gonaïves", "Artibonite", "Gonaïves"), ("gonaives", "Artibonite", "Gonaïves"),
    ("saint-marc", "Artibonite", "Saint-Marc"), ("st-marc", "Artibonite", "Saint-Marc"),
    ("st marc", "Artibonite", "Saint-Marc"), ("gros-morne", "Artibonite", "Gros-Morne"),
    ("ennery", "Artibonite", "Ennery"), ("l'estère", "Artibonite", "L'Estère"), ("anse rouge", "Artibonite", "Anse-Rouge"),
    ("desdunes", "Artibonite", "Desdunes"), ("bouyer", "Artibonite", "Bouyer"), ("grand-fond", "Artibonite", "Grand-Fond"),
    ("petit-bourg", "Artibonite", "Petit-Bourg"), ("saint-michel de l'attalaye", "Artibonite", "Saint-Michel-de-l'Attalaye"),
    ("cap-haïtien", "Nord", "Cap-Haïtien"), ("cap haitien", "Nord", "Cap-Haïtien"),
    ("cap-haitien", "Nord", "Cap-Haïtien"), ("quartier-morin", "Nord", "Quartier-Morin"),
    ("quartier morin", "Nord", "Quartier-Morin"), ("morne-pelé", "Nord", "Morne-Pelé"),
    ("morne pele", "Nord", "Morne-Pelé"), ("plaisance", "Nord", "Plaisance"), ("borgne", "Nord", "Borgne"),
    ("port-margot", "Nord", "Port-Margot"), ("limonade", "Nord", "Limonade"), ("okip", "Nord", "Okp"),
    ("bahon", "Nord", "Bahon"), ("milot", "Nord", "Milot"), ("perade", "Nord", "Pèredeville"),
    ("citerne", "Nord", "Citerne"), ("saint-louis", "Nord", "Saint-Louis-du-Nord"),
    ("port-de-paix", "Nord-Ouest", "Port-de-Paix"), ("môle-saint-nicolas", "Nord-Ouest", "Môle-Saint-Nicolas"),
    ("bombardopolis", "Nord-Ouest", "Bombardopolis"), ("chansolme", "Nord-Ouest", "Chansolme"),
    ("baie de henne", "Nord-Ouest", "Baie-de-Henne"), ("anse noire", "Nord-Ouest", "Anse-Noire"),
    ("ouanaminthe", "Nord-Est", "Ouanaminthe"), ("fort-liberté", "Nord-Est", "Fort-Liberté"),
    ("vallieres", "Nord-Est", "Vallières"), ("ferrier", "Nord-Est", "Ferrier"), ("capotille", "Nord-Est", "Capotille"),
    ("trou-du-nord", "Nord-Est", "Trou-du-Nord"),
    ("maïssade", "Centre", "Maïssade"), ("maissade", "Centre", "Maïssade"), ("hinche", "Centre", "Hinche"),
    ("cerca-la-source", "Centre", "Cerca-la-Source"), ("thomonde", "Centre", "Thomonde"),
    ("sacredoux", "Centre", "Sacredoux"), ("bailo", "Centre", "Bailo"), ("lascahobas", "Centre", "Lascahobas"),
    ("mirebalais", "Centre", "Mirebalais"), ("saut-d'eau", "Centre", "Saut-d'Eau"),
    ("boucan-carré", "Centre", "Boucan-Carré"), ("cayes-carreaux", "Centre", "Cayes-Carreaux"),
    ("sans souci", "Centre", "Sans-Souci"), ("beladere", "Centre", "Beladère"),
    ("jacmel", "Sud-Est", "Jacmel"), ("bainet", "Sud-Est", "Bainet"), ("belle-anse", "Sud-Est", "Belle-Anse"),
    ("marigot", "Sud-Est", "Marigot"), ("cayes-jacmel", "Sud-Est", "Cayes-Jacmel"),
    ("fond-des-nègres", "Sud-Est", "Fond-des-Nègres"), ("thiotte", "Sud-Est", "Thiotte"),
    ("les cayes", "Sud", "Les Cayes"), ("aquin", "Sud", "Aquin"), ("corail", "Sud", "Corail"),
    ("camp-perrin", "Sud", "Camp-Perrin"), ("chardonnières", "Sud", "Chardonnières"),
    ("cavaillon", "Sud", "Cavaillon"), ("manoir", "Sud", "Manoir"), ("port-salut", "Sud", "Port-Salut"),
    ("saint-jean-du-sud", "Sud", "Saint-Jean-du-Sud"), ("coteaux", "Sud", "Coteaux"),
    ("grands-bois", "Sud", "Grands-Bois"), ("jean-rabel", "Sud", "Jean-Rabel"),
    ("miragoâne", "Nippes", "Miragoâne"), ("miragoane", "Nippes", "Miragoâne"), ("anse-à-veau", "Nippes", "Anse-à-Veau"),
    ("petit-trou-de-nippes", "Nippes", "Petit-Trou-de-Nippes"), ("arnema", "Nippes", "Arnema"),
    ("baradères", "Nippes", "Baradères"), ("nerette", "Nippes", "Nérette"), ("vieux-carreau", "Nippes", "Vieux-Carreau"),
    # Zones d'habitation telles que le registre les écrit (quartiers, lotissements, routes coupées).
    # Volontairement limité à ce qui est sûr : une commune mal rattachée ferait voir un MEOL au mauvais
    # responsable départemental, ce qui pis serait qu'un département laissé à déterminer.
    ("bon-repos", "Ouest", "Port-au-Prince"), ("lilavois", "Ouest", "Croix-des-Bouquets"),
    ("canaan", "Ouest", "Canaan"), ("sarthe", "Ouest", "Tabarre"), ("onaville", "Ouest", "Tabarre"),
    ("clercine", "Ouest", "Port-au-Prince"), ("mais-gaté", "Ouest", "Port-au-Prince"),
    ("fontamara", "Ouest", "Port-au-Prince"), ("fort-jacques", "Ouest", "Pétion-Ville"),
    ("thomassin", "Ouest", "Pétion-Ville"), ("soisson", "Ouest", "Pétion-Ville"),
    ("cite-solaire", "Ouest", "Cité-Soleil"),
    ("village des rapatries", "Ouest", "Cité-Soleil"), ("solidarite", "Ouest", "Cité-Soleil"),
    ("mariani", "Ouest", "Port-au-Prince"), ("bicentenaire", "Ouest", "Delmas"),
    ("préférence", "Ouest", "Delmas"), ("ormond", "Ouest", "Delmas"), ("delams", "Ouest", "Delmas"),
    ("nazon", "Ouest", "Port-au-Prince"), ("plateau central", "Ouest", "Port-au-Prince"),
    ("peguyville", "Ouest", "Port-au-Prince"), ("pacot", "Ouest", "Port-au-Prince"),
    ("laboule", "Ouest", "Pétion-Ville"), ("ona-ville", "Ouest", "Tabarre"),
    ("p-au-p", "Ouest", "Port-au-Prince"), ("cays", "Sud", "Les Cayes"),
    ("ganthier", "Ouest", "Ganthier"), ("gantier", "Ouest", "Ganthier"), ("malpasse", "Ouest", "Malpasse"),
    ("cul-de-sac", "Ouest", "Cul-de-Sac"), ("pap", "Ouest", "Port-au-Prince"),
    ("limbé", "Nord", "Limbé"), ("pignon", "Nord", "Pignon"), ("dondon", "Nord", "Dondon"),
    ("acul", "Nord", "Acul-du-Nord"), ("vertières", "Nord", "Vertières"), ("capois", "Nord", "Cap-Haïtien"),
    ("ouanamithe", "Nord-Est", "Ouanaminthe"), ("ouananminthe", "Nord-Est", "Ouanaminthe"),
    ("caracol", "Nord-Est", "Caracol"), ("nord-est", "Nord-Est", None), ("nord-ouest", "Nord-Ouest", None),
    ("petite-rivière", "Artibonite", "Petite-Rivière-de-l'Artibonite"), ("artibonite", "Artibonite", None),
    ("nippes", "Nippes", None), ("grand'anse", "Grand'Anse", None),
    ("cayes", "Sud", "Les Cayes"), ("sud", "Sud", None), ("nord", "Nord", None), ("sud-est", "Sud-Est", None),
]

# Adresses hors d'Haïti : la FPH a des bodies de la diaspora. Un département haïtien n'a alors aucun
# sens — c'est une mention à vérifier par un humain, pas une case à remplir.
FOREIGN = ("fort lauderdale", "florida", "new york", "georgia", "montreal", "nouvelle orleans",
           "strasbourg", "france", "guadeloupe", "guyane", "republique dominicaine", "usa")


def _ascii(text):
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def norm_key(text):
    """Clé de rapprochement : minuscule, sans accents ni ponctuation superflue."""
    t = _ascii(text or "").lower()
    t = re.sub(r"\(.*?\)", " ", t)              # sigles entre parenthèses : ignorés
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return " ".join(t.split())


def cell_text(lines):
    """Texte d'une cellule multi-lignes, collé avec un espace."""
    out = " ".join(l.strip() for l in lines if l.strip())
    out = re.sub(r"\s+", " ", out).strip()
    return "" if out in EMPTY_MARKS else out


def cell_glued(lines):
    """Texte d'une cellule coupée en plein milieu d'un mot (téléphones, e-mails) : collé sans espace."""
    out = "".join(l.strip() for l in lines if l.strip())
    out = re.sub(r"\s*/\s*", " / ", out)
    out = re.sub(r"\s+", " ", out).strip()
    return "" if out in EMPTY_MARKS else out


def column_cuts(lines):
    """Bords de colonnes déduits du document lui-même (les deux registres ne sont pas alignés pareil) :
    les débuts de segments forment 5 grappes, une par colonne, séparées par de larges vides."""
    starts = sorted({m.start() for line in lines for m in GAP.finditer(line) if m.group().strip()})
    clusters, current = [], []
    for s in starts:
        if current and s - current[-1] > 20:
            clusters.append(current)
            current = []
        current.append(s)
    if current:
        clusters.append(current)
    if len(clusters) < len(COLS):
        sys.exit(f"Colonnes insuffisantes pour découper le tableau ({len(clusters)} grappes observées)")
    clusters = clusters[:len(COLS)]
    return [(clusters[i][-1] + clusters[i + 1][0]) // 2 for i in range(len(clusters) - 1)]


def split_segments(line, cuts):
    """Découpe une ligne en (colonne, texte) à partir des runs de 3+ espaces."""
    segments = []
    for m in GAP.finditer(line):
        text = re.sub(r"\s+", " ", m.group()).strip()
        if not text:
            continue
        col = bisect.bisect_right(cuts, m.start())
        if segments and segments[-1][0] == col:
            segments[-1] = (col, segments[-1][1] + " " + text)
        else:
            segments.append((col, text))
    return segments


def is_chrome(line):
    """Lignes d'ornement du PDF (en-tête de page, titre, pied de page) à ignorer."""
    low = line.lower()
    if "liste des meols" in low or "triée par ordre" in low or "missions / eglises" in low:
        return True
    if "responsable(s)" in low and "adresse" in low:
        return True
    if "(fph)" in low and "page" in low and "/" in line:
        return True
    if "nombre total d'entr" in low:
        return True
    return False


def read_blocks(path):
    """-> (blocs, total annoncé). Un bloc = les lignes d'une même ligne du tableau, séparées du bloc
    voisin par une ligne vide. Chaque bloc porte la page dont il vient et dit s'il est le premier de
    sa page : c'est là que reportlab peut couper une entrée en deux."""
    try:
        from pypdf import PdfReader
    except ImportError:
        sys.exit("pypdf est absent : pip install pypdf (voir scripts/requirements.txt)")
    pairs, announced = [], None
    for page_number, page in enumerate(PdfReader(path).pages):
        if page_number:
            pairs.append((page_number, ""))     # force une rupture de bloc entre deux pages (voir docstring)
        for raw in (page.extract_text(extraction_mode="layout") or "").splitlines():
            if "nombre total d'entr" in raw.lower():
                m = re.search(r"(\d+)", raw)
                announced = int(m.group(1)) if m else announced
            if is_chrome(raw):
                continue
            pairs.append((page_number, raw))

    blocks, current = [], None
    for page_number, raw in pairs:
        if not raw.strip():
            current = None
            continue
        if current is None:
            current = {"page": page_number, "lines": []}
            blocks.append(current)
        current["lines"].append(raw)
    seen = set()
    for b in blocks:
        b["first_on_page"] = b["page"] not in seen
        seen.add(b["page"])
    return blocks, announced


def block_columns(block, cuts):
    """Bloc -> une cellule par colonne. Le texte d'une même colonne est collé ligne par ligne."""
    cols = {c: [] for c in COLS}
    for l in block["lines"]:
        for col, text in split_segments(l, cuts):
            cols[COLS[col]].append(text)
    return {
        "name": cell_text(cols["name"]),
        "people": cell_text(cols["people"]),
        "phones": cell_glued(cols["phones"]),
        "emails": cell_glued(cols["emails"]),
        "address": cell_text(cols["address"]),
    }


def order_key(name):
    """Clé de tri du registre : le PDF est « trié par ordre alphabétique », ce qui sert de contrôle
    structurel — une entrée qui casse l'ordre est une entrée mal coupée ou mal raccordée."""
    t = _ascii(name or "").lower()
    t = re.sub(r"\([^)]*\)", " ", t)
    words = [w for w in re.split(r"[^a-z0-9]+", t) if w]
    return " ".join(words[:3])


def split_email_signal(prev, frag):
    """Signe objectif d'une entrée coupée en deux par un saut de page : les deux moitiés de la colonne
    « e-mail » sont invalides chacune pour soi et forment une adresse valide recollées. Une adresse
    complète d'un côté, ou deux adresses distinctes, ne déclenchent jamais cette règle."""
    if not prev["emails"] or not frag["emails"]:
        return None
    if clean_emails(prev["emails"]) or clean_emails(frag["emails"]):
        return None
    joined = re.sub(r"\s+", "", prev["emails"] + frag["emails"])
    return joined if EMAIL_RE.match(joined) else None


def merge_reason(prev, frag):
    """Pourquoi le premier bloc d'une page (frag) est en réalité la suite de l'entrée précédente.
    Renvoie None si c'est bel et bien une nouvelle entrée. Les critères sont objectifs et verificables :
    pas de nom dans la colonne « nom », un nom qui casse l'ordre alphabétique (le registre est trié,
    donc un nom qui remonte dans l'alphabet ne peut pas être un début), ou un e-mail recoupé."""
    if not frag["name"]:
        return "colonne « nom » vide"
    if order_key(frag["name"]) < order_key(prev["name"]):
        return f"ordre alphabétique brisé ({prev['name']!r} -> {frag['name']!r})"
    joined = split_email_signal(prev, frag)
    if joined:
        return f"e-mail coupé à la frontière de page, recollé en {joined}"
    return None


def parse_pdf(path):
    """-> (entrées, total annoncé par le PDF ou None).

    Une entrée coupée par un saut de page revient en début de page suivante. Le raccordement se
    décide avec `merge_reason` ; chaque décision est consignée dans `entry["boundaries"]` pour que
    le rapport humain puisse relire les cas limites au lieu de les avaler en silence.
    """
    blocks, announced = read_blocks(path)
    cuts = column_cuts([l for b in blocks for l in b["lines"]])
    entries = []
    for block in blocks:
        entry = block_columns(block, cuts)
        entry["page"] = block["page"]
        previous = entries[-1] if entries else None
        # Un bloc peut être une suite quand il n'a pas de nom (retour à la ligne sans colonne « nom »)
        # ou quand il ouvre une page (coupe nette au milieu d'une entrée).
        reason = None
        if previous is not None and (not entry["name"] or block["first_on_page"]):
            reason = merge_reason(previous, entry)
        if reason is not None:
            for key in ("people", "phones", "emails", "address"):
                if entry[key]:
                    # Un e-mail coupé se recolle sans espace (le PDF coupait au milieu du mot), les
                    # autres colonnes sont des mots entiers : une espace les sépare proprement.
                    sep = "" if key == "emails" and split_email_signal(previous, entry) else " "
                    previous[key] = (previous[key] + sep + entry[key]).strip()
            if entry["name"]:
                previous["name"] = (previous["name"] + " " + entry["name"]).strip()
            previous["boundaries"].append({"page": block["page"], "reason": reason,
                                           "fragment": entry["name"] or "(sans nom)"})
            continue
        entry["boundaries"] = []
        if block["first_on_page"] and previous is not None:
            entry["boundaries"].append({"page": block["page"], "reason": "nouvelle entrée",
                                        "fragment": entry["name"]})
        if not entry["name"]:
            entry["name"] = "(sans nom — à vérifier)"
        entries.append(entry)
    return entries, announced


def order_violations(entries):
    """Contrôle structurel : listes des entrées qui cassent l'ordre alphabétique du registre."""
    out = []
    for i in range(1, len(entries)):
        if order_key(entries[i]["name"]) < order_key(entries[i - 1]["name"]):
            out.append((i, entries[i - 1]["name"], entries[i]["name"]))
    return out


def classify_type(entry):
    """org_type : le vocabulaire du serveur (permissions.ORG_TYPES) est complété par les sortes
    propres aux MEOL (mission, église, ligue de pasteurs)."""
    name = _ascii(entry["name"].lower())
    if re.search(r"\bcultes reformes\b|\bepiscopal\b", name):
        return "eglise"
    if "ligue" in name or "confraternite" in name or "coalition" in name:
        return "ligue_pasteurs"
    if name.startswith("mission") or re.search(r"\bmission\b", name):
        return "mission"
    if re.search(r"\beglise(s)?\b|\bassemblee(s)? chretienne\b|\bparoisse\b", name):
        return "eglise"
    if re.search(r"\buniversite\b|\bcollege\b|\binstitut\b|\becole\b|\bseminaire\b|\bfaculte\b|\binuka\b", name):
        return "ecole"
    if re.search(r"\bassociation\b|\bfederation\b|\bconfederation\b|\bconnexion\b|\bconseil\b|\balliance\b"
                 r"|\bunion\b|\bcommunaute\b|\bconference\b|\bmouvement\b|\bplateforme\b|\bregroupement\b", name):
        return "association"
    if re.search(r"\bdeveloppement\b|\bhumanitaire\b|\bsecours\b|\bsoutien\b|\baide\b|\bjeunesse\b|\bfemmes\b"
                 r"|\bsante\b|\beducation\b|\bhavidec\b|\bvihamo\b", name):
        return "oeuvre_sociale"
    return "autre"


# Le serveur ne connaît que six types d'organisation (permissions.ORG_TYPES), validés à la création
# comme à la mise à jour : écrire « mission » en base produirait une ligne impossible à modifier depuis
# l'API. Le registre MEOL est plus fin que le schéma, donc la nuance est gardée à côté (`meol_kind`)
# pour la relecture, et seule une valeur admise est écrite.
ORG_TYPE_OF = {"eglise": "ministere", "mission": "ministere", "ligue_pasteurs": "association",
               "ecole": "ecole", "association": "association", "oeuvre_sociale": "oeuvre_sociale",
               "autre": "autre"}


def _place(text):
    """Texte rendu comparable : accents et tirets deviennent des espaces, le reste disparaît. Le
    registre écrit « Pétion-Ville », « Petion-ville » et « Pignon Haiti » ; le PDF coupe aussi les mots
    en fin de ligne, donc « Port-au- Prince » se rencontre réellement."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", _ascii(text or "").lower()).split())


def locate(text):
    """-> (département, commune) du lieu le plus précis trouvé dans un texte, (None, None) sinon.
    Le plus long mot-clé gagne : « cayes-jacmel » (Sud-Est) avant « cayes » (Sud), « nord-ouest »
    avant « nord ». Aucun classement par défaut : introuvable veut dire introuvable."""
    hay = _place(text)
    best = None
    for keyword, dept, commune in GEOGRAPHY:
        key = _place(keyword)
        if re.search(r"(?<![a-z0-9])" + re.escape(key) + r"(?![a-z0-9])", hay):
            if best is None or len(key) > len(best[0]):
                best = (key, dept, commune)
    return (best[1], best[2]) if best else (None, None)


def derive_department(entry):
    """Département déduit de l'adresse, sinon du nom. Aucune donnée inventée : (None, None) si introuvable."""
    for source in ("address", "name"):
        dept, commune = locate(entry[source])
        if dept:
            return dept, commune, source
    if any(k in _place(entry["address"]) for k in FOREIGN):
        return None, None, "etranger"
    return None, None, None


def split_people(text):
    if not text:
        return []
    parts = re.split(r"\s*/\s*", text)
    return [re.sub(r"\s+", " ", p).strip(" ,;") for p in parts if p.strip(" ,;") not in EMPTY_MARKS]


def split_list(text, sep="/"):
    if not text:
        return []
    return [p.strip(" ,;") for p in text.split(sep) if p.strip(" ,;") not in EMPTY_MARKS]


EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


def email_parts(text):
    """-> (adresses valides, fragments écartés). Le registre coupe les adresses en milieu de ligne et
    mélange accents et ASCII : « francoisgenesca@gmail .com » devient valide en retirant l'espace,
    « policehaiti@yahoo.fr » en retirant l'accent. Ce qui résiste part dans la liste à vérifier,
    jamais à la poubelle."""
    valid, rejected = [], []
    for candidate in split_list(text):
        fixed = _ascii(candidate).replace(" ", "").lower().rstrip(".,;")
        (valid if EMAIL_RE.match(fixed) else rejected).append(fixed or candidate.strip())
    return valid, rejected


def clean_emails(text):
    return email_parts(text)[0]


def clean_phones(text):
    out = []
    for candidate in split_list(text):
        fixed = re.sub(r"[^0-9+()\- ]", "", _ascii(candidate)).strip()
        fixed = re.sub(r"\s+", "", fixed)
        digits = re.sub(r"\D", "", fixed)
        if len(digits) >= 7:
            out.append(fixed)
    return out


UNKNOWN_DEPT = "À déterminer"          # département impossible à déduire : jamais inventé, jamais publié


def enrich(entry):
    """Entrée brute -> entrée prête pour la base, avec ce qui a dû être écarté (traçable dans le rapport)."""
    emails, rejected = email_parts(entry["emails"])
    phones = clean_phones(entry["phones"])
    dept, commune, source = derive_department(entry)
    kind = classify_type(entry)
    name = entry["name"]
    return {
        "name": name,
        "name_key": " ".join(name.lower().split()),
        "match_key": norm_key(name),
        "meol_kind": kind,
        "org_type": ORG_TYPE_OF[kind],
        "department": dept or UNKNOWN_DEPT,
        "commune": commune,
        "dept_source": source,
        "address": entry["address"] or None,
        "people": split_people(entry["people"]),
        "emails": emails,
        "rejected_emails": rejected,
        "phones": phones,
        "page": entry.get("page"),
        "boundaries": entry.get("boundaries", []),
        "raw": entry,
    }


def load(path):
    entries, announced = parse_pdf(path)
    enriched = [enrich(e) for e in entries]
    if announced is not None and announced != len(enriched):
        print(f"ATTENTION : le PDF annonce {announced} entrées, {len(enriched)} lues.", file=sys.stderr)
    return enriched, announced


def _contact(e):
    return {"contact_email": e["emails"][0] if e["emails"] else None,
            "contact_phone": e["phones"][0] if e["phones"] else None}


def _extra(e):
    """Ce qui ne rentre pas dans un seul champ, ou ce qui a été déduit : à vérifier par un humain,
    pas à jeter. Chaque mention porte un code pour que le rapport soit triable par nature de doute."""
    notes = []
    if len(e["emails"]) > 1:
        notes.append(("contacts", "autres e-mails : " + ", ".join(e["emails"][1:])))
    if len(e["phones"]) > 1:
        notes.append(("contacts", "autres téléphones : " + ", ".join(e["phones"][1:])))
    if e["rejected_emails"]:
        notes.append(("email", "e-mails non valides : " + ", ".join(e["rejected_emails"])))
    if e["dept_source"] == "etranger":
        notes.append(("departement", "adresse hors Haïti : aucun département haïtien ne s'applique"))
    elif e["department"] == UNKNOWN_DEPT:
        notes.append(("departement", "département non déduit"))
    elif not e["commune"]:
        notes.append(("departement", "département déduit du nom, pas de commune : " + e["dept_source"]))
    for b in e["boundaries"]:
        if b["reason"] != "nouvelle entrée":
            notes.append(("coupe", f"raccordé page {b['page'] + 1} : {b['reason']}"))
    if len(e["people"]) > 1:
        notes.append(("hierarchie", f"{len(e['people'])} responsables nommés, le premier est tenu pour principal"))
    if not e["people"]:
        notes.append(("hierarchie", "aucun responsable nommé dans le registre"))
    return notes


def compare(old, new):
    """Rapport markdown : ce qui a disparu, ce qui est apparu, ce qui a changé entre deux registres."""
    old_by, new_by = {}, {}
    dupes_new = []
    for e in old:
        old_by.setdefault(e["match_key"], e)
    for e in new:
        if e["match_key"] in new_by:
            dupes_new.append(e["name"])
        else:
            new_by[e["match_key"]] = e
    gone = [k for k in old_by if k not in new_by]
    added = [k for k in new_by if k not in old_by]
    kept = [k for k in new_by if k in old_by]

    lines = ["# Comparaison des listes MEOL", "",
             f"- Ancien registre : **{len(old_by)}** entrées (après rapprochement des noms)",
             f"- Nouveau registre : **{len(new_by)}** entrées",
             f"- Communes aux deux : **{len(kept)}** · apparues : **{len(added)}** · disparues : **{len(gone)}**", ""]
    if dupes_new:
        lines += ["## Doublons dans le nouveau registre (même nom normalisé)",
                  "", *[f"- {n}" for n in dupes_new], ""]
    if gone:
        lines += ["## Présent dans l'ancien, absent du nouveau", ""]
        lines += [f"- {old_by[k]['name']}" for k in sorted(gone, key=lambda k: old_by[k]["name"].lower())] + [""]
    if added:
        lines += ["## Ajouté dans le nouveau registre", ""]
        for k in sorted(added, key=lambda k: new_by[k]["name"].lower()):
            e = new_by[k]
            lines.append(f"- {e['name']} ({e['org_type']}, {e['department']})")
        lines.append("")
    changed = []
    for k in kept:
        a, b = old_by[k], new_by[k]
        diffs = []
        for field, label in (("address", "adresse"), ("people", "responsables"),
                             ("phones", "téléphones"), ("emails", "e-mails")):
            if a["raw"][field] != b["raw"][field]:
                diffs.append(f"{label} : `{a['raw'][field] or '—'}` → `{b['raw'][field] or '—'}`")
        if diffs:
            changed.append((b["name"], diffs))
    lines += [f"## Modifiées entre les deux registres ({len(changed)})", ""]
    for name, diffs in sorted(changed, key=lambda c: c[0].lower()):
        lines.append(f"- {name}")
        lines += [f"  - {d}" for d in diffs]
    lines.append("")
    return "\n".join(lines)


def _server_vocab():
    """Vocabulaire du serveur. `parse` et `compare` restent autonomes (ils n'importent rien du serveur),
    d'où la constante `UNKNOWN_DEPT` plus haut ; mais les deux chemins d'écriture vérifient qu'ils
    tombent d'accord avec le serveur : sinon une fiche importée serait refusée plus tard par l'API, et
    le registre serait à moitié réparable."""
    sys.path.insert(0, os.path.join(ROOT, "server"))
    from app.permissions import DEPARTMENTS, DEPARTMENT_UNKNOWN, LEADER_FUNCTIONS, ORG_TYPES
    if UNKNOWN_DEPT != DEPARTMENT_UNKNOWN:
        sys.exit(f"« {UNKNOWN_DEPT} » n'est plus la valeur du serveur (« {DEPARTMENT_UNKNOWN} ») : "
                 "aligner UNKNOWN_DEPT dans ce script")
    return DEPARTMENTS, DEPARTMENT_UNKNOWN, LEADER_FUNCTIONS, ORG_TYPES


def import_entries(entries, actor_username, dry_run):
    """Écrit dans la base via les modèles du serveur. Idempotent : relancer ne duplique rien."""
    sys.path.insert(0, os.path.join(ROOT, "server"))
    from sqlalchemy import func, select

    from app.db import SessionLocal
    from app.models import AuditLog, EntityHistory, Leader, LeaderAssignment, Organization, User
    DEPARTMENTS, _UNKNOWN, LEADER_FUNCTIONS, ORG_TYPES = _server_vocab()

    # Contrôle du vocabulaire AVANT la première écriture : l'API refuserait plus tard un type ou un
    # département hors liste, et la fiche importée par-dessus le serveur serait alors impossible à
    # corriger depuis un écran. Mieux vaut refaire échouer l'import tout de suite.
    for e in entries:
        if e["org_type"] not in ORG_TYPES:
            sys.exit(f"Type d'organisation hors vocabulaire pour {e['name']!r} : {e['org_type']!r}")
    hors_liste = sorted({e["department"] for e in entries} - set(DEPARTMENTS) - {_UNKNOWN})
    if hors_liste:
        sys.exit("Départements hors vocabulaire : " + ", ".join(hors_liste))

    summary = Counter()
    review = []
    with SessionLocal() as db:
        actor = None
        if actor_username:
            actor = db.scalar(select(User).where(func.lower(User.username) == actor_username.lower()))
            if actor is None:
                actor = db.scalar(select(User).where(func.lower(User.email) == actor_username.lower()))
            if actor is None:
                sys.exit(f"Compte inconnu pour l'auteur de l'import : {actor_username}")
        today = date.today()
        for e in entries:
            fields = {"name": e["name"][:250], "org_type": e["org_type"], "department": e["department"],
                      "commune": e["commune"], "address": e["address"], **_contact(e)}
            org = db.scalar(select(Organization).where(Organization.name_key == e["name_key"]))
            if org is None:
                org = Organization(**fields, name_key=e["name_key"], validation_status="draft",
                                   affiliation_status="pending", version=1,
                                   created_by=actor.id if actor else None)
                db.add(org)
                db.flush()
                db.add(EntityHistory(entity_type="organization", entity_id=org.id, version=1,
                                     action="imported", changes={k: v for k, v in fields.items() if v},
                                     actor_id=actor.id if actor else None))
                db.add(AuditLog(actor_id=actor.id if actor else None, action="organization.imported",
                                target_type="organization", target_id=org.id,
                                detail={"source": "liste MEOL", "department": fields["department"]}))
                summary["organisations créées"] += 1
            else:
                diffs = {k: v for k, v in fields.items() if getattr(org, k) != v}
                if diffs:
                    for k, v in diffs.items():
                        setattr(org, k, v)
                    if org.validation_status in ("approved", "published", "pending"):
                        diffs["validation_status"] = "pending"     # règle du projet : rien de non validé ne reste public
                        org.validation_status = "pending"
                    org.version += 1
                    db.add(EntityHistory(entity_type="organization", entity_id=org.id, version=org.version,
                                         action="imported_updated", changes=diffs,
                                         actor_id=actor.id if actor else None))
                    db.add(AuditLog(actor_id=actor.id if actor else None, action="organization.imported_updated",
                                    target_type="organization", target_id=org.id,
                                    detail={"fields": sorted(diffs)}))
                    summary["organisations mises à jour"] += 1
                else:
                    summary["organisations inchangées"] += 1
            for index, person in enumerate(e["people"]):
                if len(person) < 2:
                    continue
                leader = db.scalar(select(Leader).where(Leader.organization_id == org.id,
                                                        func.lower(Leader.full_name) == person.lower()))
                # Déduction partagée avec l'enrolement par l'API (voir `_leader_function`).
                function = _leader_function(person, index)
                if leader is None:
                    leader = Leader(full_name=person[:200], function=function, organization_id=org.id,
                                    admin_status="active", version=1, created_by=actor.id if actor else None)
                    db.add(leader)
                    db.flush()
                    db.add(LeaderAssignment(leader_id=leader.id, organization_id=org.id, function=function,
                                            start_date=today, recorded_by=actor.id if actor else None))
                    db.add(EntityHistory(entity_type="leader", entity_id=leader.id, version=1, action="imported",
                                         changes={"function": function, "organization_id": org.id},
                                         actor_id=actor.id if actor else None))
                    summary["responsables créés"] += 1
                elif leader.function != function and function in LEADER_FUNCTIONS:
                    leader.function = function
                    leader.version += 1
                    summary["responsables mis à jour"] += 1
            notes = _extra(e)
            if notes:
                review.append((e["name"], notes))
        if dry_run:
            db.rollback()
        else:
            db.commit()
    return summary, review


def _leader_function(person, index):
    """Le registre ne hiérarchise pas les responsables : le premier nommé est tenu pour principal,
    les autres vont en « autre ». Déduction, donc notée dans le rapport. Partagée entre l'écriture en
    base et l'enrolement par l'API : la même liste ne doit pas donner deux registres différents selon
    l'outil employé."""
    titled = re.match(r"^(pasteur|pastor|past|rev|rv)\b", _ascii(person.lower()))
    return (("pasteur_principal" if titled else "responsable_principal")
            if index == 0 else "autre")


def _server_key(name):
    """Clé de doublon telle que l'API l'applique (`Organization.name_key`) : minuscule, espaces
    réduits — mais les accents et la ponctuation ne sont pas ignorés, contrairement à `norm_key` qui
    sert à raccorder deux pages du PDF. Chercher avec la mauvaise clé ferait croire une fiche absente
    là où le serveur répondrait « de même nom existe déjà »."""
    return " ".join((name or "").lower().split())


def _api_find_org(client, name):
    offset = 0
    while True:
        page = client.get("/api/v1/organizations",
                          params={"q": name[:100], "limit": 200, "offset": offset}).json()
        hit = next((o for o in page if _server_key(o["name"]) == _server_key(name)), None)
        if hit is not None or len(page) < 200:
            return hit
        offset += 200


def _api_upsert_org(client, fields, dry_run):
    """Une fiche -> 'creee' / 'mise_a_jour' / 'inchangee' / 'refusee'. Le 409 n'est pas une erreur :
    c'est la preuve que la fiche existe déjà, et le rejeu d'un même registre doit finir inchangé."""
    if dry_run:
        existing = _api_find_org(client, fields["name"])
        if existing is None:
            return "creee", None
        diffs = {k: v for k, v in fields.items() if existing.get(k) != v}
        return ("mise_a_jour" if diffs else "inchangee"), existing
    r = client.post("/api/v1/organizations", json=fields)
    if r.status_code == 201:
        return "creee", r.json()
    if r.status_code == 422 and "contact_email" in r.text:
        # Une adresse du registre que le serveur juge invalide ne doit pas faire rejeter toute la
        # fiche : on la laisse de côté (elle est déjà signalée dans le rapport) et on repasse.
        fields = {**fields, "contact_email": None}
        r = client.post("/api/v1/organizations", json=fields)
        if r.status_code == 201:
            return "creee", r.json()
    if r.status_code == 409:
        existing = _api_find_org(client, fields["name"])
        if existing is None:
            return "refusee", "doublon annoncé par le serveur mais aucune fiche retrouvée " \
                             "(hors de votre périmètre ?)"
        diffs = {k: v for k, v in fields.items() if existing.get(k) != v}
        if not diffs:
            return "inchangee", existing
        p = client.patch(f"/api/v1/organizations/{existing['id']}",
                         json={"version": existing["version"], **diffs})
        if p.status_code != 200:
            return "refusee", f"PATCH {p.status_code} : {p.text[:160]}"
        return "mise_a_jour", p.json()
    return "refusee", f"POST {r.status_code} : {r.text[:160]}"


def _api_enroll_leaders(client, e, org_id):
    """Responsables : on retrouve d'abord ceux déjà rattachés à la fiche. Le serveur ne considère un
    doublon que si le nom ET la fonction correspondent ; créer à l'aveugle un responsable dont la
    fonction a changé laisserait deux lignes pour la même personne."""
    created, updated, refused = 0, 0, []
    known = {_server_key(l["full_name"]): l
             for l in client.get("/api/v1/leaders", params={"organization_id": org_id, "limit": 500}).json()}
    for index, person in enumerate(e["people"]):
        if len(person) < 2:
            continue
        function = _leader_function(person, index)
        row = known.get(_server_key(person))
        if row is None:
            r = client.post("/api/v1/leaders", json={"full_name": person[:200], "function": function,
                                                     "organization_id": org_id})
            if r.status_code == 201:
                created += 1
            else:
                refused.append(f"{person} : POST {r.status_code} {r.text[:100]}")
        elif row["function"] != function:
            p = client.patch(f"/api/v1/leaders/{row['id']}",
                             json={"version": row["version"], "function": function})
            if p.status_code == 200:
                updated += 1
            else:
                refused.append(f"{person} : PATCH {p.status_code} {p.text[:100]}")
    return created, updated, refused


def import_entries_api(entries, base, identifier, password, ca=None, dry_run=False):
    """Enrole le registre **par l'API** (`POST`/`PATCH /api/v1/organizations`) au lieu d'écrire dans la
    base. C'est le seul chemin quand la base tourne dans un conteneur sans port publié, et le seul qui
    applique les règles du serveur au moment de l'écriture : droits, vocabulaire, versionnage,
    historique, audit.

    Rejouable et reprenable : chaque fiche est écrite pour son propre compte, donc un incident en cours
    de route n'abîme rien de ce qui est déjà passé — relancer l'import reprend où il s'est arrêté et
    laisse inchangées les fiches déjà entrées. C'est ce qui permet d'enroler au fil de l'eau.
    """
    try:
        import httpx
    except ImportError:
        sys.exit("L'enrolement par l'API a besoin de httpx : pip install httpx")
    sys.path.insert(0, os.path.join(ROOT, "server"))
    DEPARTMENTS, _UNKNOWN, _LEADER_FN, ORG_TYPES = _server_vocab()

    # Vocabulaire vérifié AVANT la première écriture : l'API rejette un type ou un département inconnu,
    # et une fiche à moitié écrite dans un registre vivant est plus difficile à reprendre qu'un refus.
    for e in entries:
        if e["org_type"] not in ORG_TYPES:
            sys.exit(f"Type d'organisation hors vocabulaire pour {e['name']!r} : {e['org_type']!r}")
    hors_liste = sorted({e["department"] for e in entries} - set(DEPARTMENTS) - {_UNKNOWN})
    if hors_liste:
        sys.exit("Départements hors vocabulaire : " + ", ".join(hors_liste))

    summary, review, refusees = Counter(), [], []
    libelles = {"creee": "organisations créées", "mise_a_jour": "organisations mises à jour",
                "inchangee": "organisations inchangées"}
    with httpx.Client(base_url=base, verify=ca or True, timeout=30) as client:
        r = client.post("/api/v1/auth/login", json={"identifier": identifier, "password": password})
        if r.status_code != 200:
            sys.exit(f"Connexion refusée par {base} ({r.status_code}) : {r.text[:200]}")
        client.headers["Authorization"] = "Bearer " + r.json()["access_token"]
        for e in entries:
            fields = {"name": e["name"][:250], "org_type": e["org_type"], "department": e["department"],
                      "commune": e["commune"], "address": e["address"], **_contact(e)}
            outcome, org = _api_upsert_org(client, fields, dry_run)
            if outcome == "refusee":
                refusees.append(f"{e['name']} : {org}")
                summary["organisations refusées"] += 1
            else:
                summary[libelles[outcome]] += 1
            if not dry_run and org:
                c, u, bad = _api_enroll_leaders(client, e, org["id"])
                summary["responsables créés"] += c
                summary["responsables mis à jour"] += u
                refusees += bad
            notes = _extra(e)
            if notes:
                review.append((e["name"], notes))
    return summary, review, refusees


def review_report(review, path):
    """Markdown des points à vérifier, groupé par nature de doute : un humain peut traiter chaque
    groupe d'un coup au lieu de relire trois cents lignes en vrac."""
    titres = {"departement": "Département à confirmer", "coupe": "Entrée raccordée après un saut de page",
              "hierarchie": "Hiérarchie des responsables déduite", "contacts": "Contacts non enregistrés",
              "email": "E-mail à relire"}
    lignes = ["# MEOL importés — points à vérifier", "",
              "Généré par `python scripts/import_meols.py import <nouveau.pdf> --review <ce fichier>`.",
              "Rien ici n'est une erreur : ce sont les **déductions** faites à partir du registre, à",
              "confirmer par un humain. Une ligne « département à confirmer » n'est visible que du niveau",
              "national tant qu'elle n'est pas tranchée.", ""]
    for code in ("departement", "coupe", "hierarchie", "email", "contacts"):
        items = [(name, [m for c, m in notes if c == code]) for name, notes in review
                 if any(c == code for c, _ in notes)]
        if not items:
            continue
        lignes += [f"## {titres[code]} ({len(items)})", ""]
        lignes += [f"- {name} — {' ; '.join(messages)}" for name, messages in items]
        lignes.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lignes) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_parse = sub.add_parser("parse", help="lit un PDF, vérifie le compte annoncé, affiche un échantillon")
    p_parse.add_argument("pdf")
    p_parse.add_argument("--show", type=int, default=5)
    p_parse.add_argument("--boundaries", action="store_true",
                         help="afficher chaque décision prise sur une frontière de page")
    p_cmp = sub.add_parser("compare", help="compare deux registres (ancien, nouveau)")
    p_cmp.add_argument("old")
    p_cmp.add_argument("new")
    p_cmp.add_argument("--out")
    p_imp = sub.add_parser("import", help="importe un registre dans la base de l'application")
    p_imp.add_argument("pdf")
    p_imp.add_argument("--db", default=None,
                       help="URL de base SQLAlchemy (défaut : FPH_DATABASE_URL, sinon server/fph_dev.db) ; "
                            "chemin réservé à l'administration, voir --api pour l'enrolement courant")
    p_imp.add_argument("--api", default=None,
                       help="URL du serveur qui tourne (ex. https://fph-serveur.local:8000) : passe par l'API "
                            "au lieu d'écrire en base — seul chemin quand la base n'est pas joignable "
                            "(conteneur sans port publié) et celui qui applique les règles du serveur")
    p_imp.add_argument("--user", default=os.environ.get("FPH_API_USER"),
                       help="compte pour l'API (droits org:write + leader:write) ; défaut : FPH_API_USER")
    p_imp.add_argument("--ca", default=os.environ.get("FPH_API_CA"),
                       help="autorité de certification du serveur (fichier), si l'API est en HTTPS interne ; "
                            "défaut : FPH_API_CA, sinon vérification système")
    p_imp.add_argument("--as", dest="actor", default=None, help="compte auteur de l'import (sinon : aucun)")
    p_imp.add_argument("--dry-run", action="store_true", help="tout vérifier sans rien écrire")
    p_imp.add_argument("--review", default=None,
                       help="écrire ici la liste des déductions à faire relire (markdown)")
    args = ap.parse_args(argv)

    if args.cmd == "parse":
        entries, announced = load(args.pdf)
        print(f"{args.pdf} : {len(entries)} entrées lues, {announced} annoncées")
        for e in entries[:args.show]:
            print(f"  - {e['name']} | {e['org_type']} ({e['meol_kind']}) | {e['department']} | "
                  f"{e['commune']} | {len(e['people'])} responsable(s) | {e['emails'][:1]} | {e['phones'][:1]}")
        if args.boundaries:
            # Tout ce qui s'est passé sur une frontière de page : chaque raccordement est relisible,
            # aucun n'est accepté en silence.
            for e in entries:
                for b in e["boundaries"]:
                    print(f"  p{b['page'] + 1:>2} {b['reason']:<26} {e['name'][:70]}")
        for i, before, after in order_violations(entries):
            print(f"  ORDRE BRISE #{i} : {before!r} -> {after!r}", file=sys.stderr)
        return 0 if announced in (None, len(entries)) else 2
    if args.cmd == "compare":
        old, _ = load(args.old)
        new, _ = load(args.new)
        report = compare(old, new)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(report + "\n")
            print(f"rapport écrit : {args.out}")
        else:
            print(report)
        return 0
    if args.api and args.db:
        sys.exit("--api et --db s'excluent : l'enrolement par l'API n'écrit pas dans la base")
    entries, announced = load(args.pdf)
    if announced is not None and announced != len(entries):
        sys.exit(f"Compte incohérent ({announced} annoncées, {len(entries)} lues) : import refusé")

    refus = []
    if args.api:
        if not args.user:
            sys.exit("--api demande un compte : --user <identifiant>, ou FPH_API_USER")
        mot_de_passe = os.environ.get("FPH_API_PASSWORD")
        if not mot_de_passe and not args.dry_run:
            # Comme pour `app.admin_cli` : un mot de passe passé en argument reste dans l'historique
            # du terminal et dans la liste des processus.
            mot_de_passe = getpass.getpass(f"Mot de passe du compte {args.user} : ")
        summary, review, refus = import_entries_api(entries, args.api, args.user, mot_de_passe,
                                                    args.ca, args.dry_run)
        cible = f"API : {args.api} (compte {args.user})"
    else:
        db_url = args.db or os.environ.get("FPH_DATABASE_URL") or _DEFAULT_DB
        os.environ["FPH_DATABASE_URL"] = db_url
        summary, review = import_entries(entries, args.actor, args.dry_run)
        cible = f"Base : {db_url}"
    mode = " — APERÇU, rien n'est écrit" if args.dry_run else ""
    print(f"{cible}{mode}")
    for label in ("organisations créées", "organisations mises à jour", "organisations inchangées",
                  "organisations refusées", "responsables créés", "responsables mis à jour"):
        print(f"  {label} : {summary[label]}")
    print(f"  entrées à vérifier : {len(review)}")
    mentions = Counter(code for _, notes in review for code, _m in notes)
    for code in ("departement", "coupe", "hierarchie", "email", "contacts"):
        if mentions[code]:
            print(f"    {code} : {mentions[code]}")
    if args.review:
        review_report(review, args.review)
        print(f"  rapport écrit : {args.review}")
    for name, notes in review[:10]:
        print(f"    - {name} : {' ; '.join(m for _c, m in notes)}")
    if len(review) > 10:
        print(f"    … {len(review) - 10} autres")
    if refus:
        # Le serveur en refuse certaines (droits, périmètre, champ invalide) : les autres sont quand même
        # entrées. Le code de sortie doit donc se remarquer dans un automatisque, et la relance reprend
        # uniquement ce qui manque.
        print(f"  Fiches non entrées : {len(refus)}", file=sys.stderr)
        for ligne in refus[:10]:
            print(f"    - {ligne}", file=sys.stderr)
        if len(refus) > 10:
            print(f"    … {len(refus) - 10} autres", file=sys.stderr)
        print("  Relancer l'import ne refait pas ce qui est déjà passé.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
