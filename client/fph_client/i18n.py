"""Textes de l'interface centralisés. Langues : fr, ht (créole haïtien), en.
Les traductions créoles sont une base de travail : à faire relire par un locuteur."""
STRINGS = {
    "fr": {"app": "FPH Connect", "login": "Connexion", "email": "E-mail ou pseudo",
           "password": "Mot de passe", "sign_in": "Se connecter", "churches": "Églises",
           "sync": "Synchroniser", "offline": "Hors ligne", "online": "En ligne",
           "pending_ops": "Modifications en attente", "conflicts": "Conflits à résoudre",
           "logout": "Déconnexion", "error_login": "Identifiants invalides",
           "last_sync": "Dernière synchronisation", "never": "jamais"},
    "ht": {"app": "FPH Connect", "login": "Konekte", "email": "Imèl oswa psedonim",
           "password": "Modpas", "sign_in": "Antre", "churches": "Legliz",
           "sync": "Senkronize", "offline": "Pa konekte", "online": "Konekte",
           "pending_ops": "Chanjman k ap tann", "conflicts": "Konfli pou rezoud",
           "logout": "Dekonekte", "error_login": "Enfòmasyon yo pa bon",
           "last_sync": "Dènye senkronizasyon", "never": "jamè"},
    "en": {"app": "FPH Connect", "login": "Sign in", "email": "Email or username",
           "password": "Password", "sign_in": "Sign in", "churches": "Churches",
           "sync": "Sync", "offline": "Offline", "online": "Online",
           "pending_ops": "Pending changes", "conflicts": "Conflicts to resolve",
           "logout": "Sign out", "error_login": "Invalid credentials",
           "last_sync": "Last sync", "never": "never"},
}


def t(lang: str, key: str) -> str:
    return STRINGS.get(lang, STRINGS["fr"]).get(key) or STRINGS["fr"].get(key, key)

STRINGS["fr"].update({"network": "Réseau local", "documents": "Documents", "back": "Retour",
    "register_device": "Enregistrer cet appareil", "device_status": "Appareil",
    "send": "Envoyer", "add_document": "Ajouter un document", "organize_click": "Classer en un clic",
    "messages": "Messages", "message_hint": "Votre message", "to_everyone": "Tout le monde",
    "pending_docs": "Documents en attente", "refresh": "Actualiser",
    "pending_approval": "en attente d'approbation", "approved": "approuvé", "revoked": "révoqué",
    "not_registered": "non enregistré"})
STRINGS["ht"].update({"network": "Rezo lokal", "documents": "Dokiman", "back": "Retounen",
    "register_device": "Anrejistre aparèy sa a", "device_status": "Aparèy",
    "send": "Voye", "add_document": "Ajoute yon dokiman", "organize_click": "Klase yo ak yon sèl klik",
    "messages": "Mesaj", "message_hint": "Mesaj ou", "to_everyone": "Tout moun",
    "pending_docs": "Dokiman k ap tann", "refresh": "Rafrechi",
    "pending_approval": "ap tann apwobasyon", "approved": "apwouve", "revoked": "revoke",
    "not_registered": "pa anrejistre"})
STRINGS["en"].update({"network": "Local network", "documents": "Documents", "back": "Back",
    "register_device": "Register this device", "device_status": "Device",
    "send": "Send", "add_document": "Add a document", "organize_click": "Organize in one click",
    "messages": "Messages", "message_hint": "Your message", "to_everyone": "Everyone",
    "pending_docs": "Documents waiting", "refresh": "Refresh",
    "pending_approval": "pending approval", "approved": "approved", "revoked": "revoked",
    "not_registered": "not registered"})

STRINGS["fr"].update({"printing": "Imprimer", "printer": "Imprimante", "copies": "Copies",
    "print_send": "Imprimer ce document", "choose_file": "Choisir un fichier (PDF, image, texte)",
    "no_printer": "Aucune imprimante autorisée", "printer_offline": "hors ligne",
    "cancel_job": "Annuler le dernier travail", "job_states": "Mes travaux d'impression"})
STRINGS["ht"].update({"printing": "Enprime", "printer": "Enprimant", "copies": "Kopi",
    "print_send": "Enprime dokiman sa a", "choose_file": "Chwazi yon fichye (PDF, imaj, tèks)",
    "no_printer": "Pa gen enprimant ki otorize", "printer_offline": "pa konekte",
    "cancel_job": "Anile dènye travay la", "job_states": "Travay enprime mwen yo"})
STRINGS["en"].update({"printing": "Print", "printer": "Printer", "copies": "Copies",
    "print_send": "Print this document", "choose_file": "Choose a file (PDF, image, text)",
    "no_printer": "No authorised printer", "printer_offline": "offline",
    "cancel_job": "Cancel last job", "job_states": "My print jobs"})

# ---- v0.8 : écrans institutionnels, états traduits, langue à chaud (traductions créoles à faire relire) ----
STRINGS["fr"].update({
    "language": "Langue", "new_church": "Nouvelle église", "church_name": "Nom officiel de l'église",
    "department": "Département", "commune": "Commune", "save": "Enregistrer", "events": "Événements",
    "invalid_form": "Nom, département et commune sont obligatoires",
    "saved_sent": "Église enregistrée sur le serveur", "saved_local": "Enregistrée sur cet appareil : sera envoyée dès que possible",
    "rejected_ops": "Refusées", "sent_count": "Envoyés", "rejected_count": "Refusés", "nothing_pending": "Rien à envoyer",
    "vs_draft": "brouillon", "vs_pending": "en attente de validation", "vs_approved": "approuvé", "vs_published": "publié",
    "vs_withdrawn": "retiré", "vs_archived": "archivé",
    "st_organized": "classé", "st_needs_review": "à vérifier", "st_duplicate": "déjà présent", "st_error": "erreur",
    "js_pending": "en attente", "js_accepted": "accepté", "js_in_progress": "en cours", "js_completed": "terminé",
    "js_transmitted": "transmis (fin non confirmable)", "js_error": "erreur", "js_cancelled": "annulé",
    "event": "Événement", "no_events": "Aucun événement", "participant_name": "Nom complet", "participant_email": "E-mail",
    "participant_phone": "Téléphone", "consent_label": "La personne accepte l'usage de ses données pour cet événement",
    "register_participant": "Inscrire", "outcome_registered": "Inscrit(e)", "outcome_waitlisted": "Événement complet : liste d'attente",
    "outcome_already": "Déjà inscrit(e)", "consent_required": "Le consentement est obligatoire",
    "stats_line": "Inscrits : {registered} · En attente : {waitlisted} · Pointés : {checked}", "you": "Vous"})
STRINGS["ht"].update({
    "language": "Lang", "new_church": "Nouvo legliz", "church_name": "Non ofisyèl legliz la",
    "department": "Depatman", "commune": "Komin", "save": "Anrejistre", "events": "Evènman",
    "invalid_form": "Non, depatman ak komin obligatwa",
    "saved_sent": "Legliz la anrejistre sou sèvè a", "saved_local": "Anrejistre sou aparèy sa a : l ap voye le sa posib",
    "rejected_ops": "Refize", "sent_count": "Voye", "rejected_count": "Refize", "nothing_pending": "Pa gen anyen pou voye",
    "vs_draft": "bouyon", "vs_pending": "ap tann validasyon", "vs_approved": "apwouve", "vs_published": "pibliye",
    "vs_withdrawn": "retire", "vs_archived": "achive",
    "st_organized": "klase", "st_needs_review": "pou verifye", "st_duplicate": "deja la", "st_error": "erè",
    "js_pending": "ap tann", "js_accepted": "aksepte", "js_in_progress": "ap fèt", "js_completed": "fini",
    "js_transmitted": "transmèt (nou pa ka konfime si li fini)", "js_error": "erè", "js_cancelled": "anile",
    "event": "Evènman", "no_events": "Pa gen evènman", "participant_name": "Non konplè", "participant_email": "Imèl",
    "participant_phone": "Telefòn", "consent_label": "Moun nan dakò pou yo itilize done li yo pou evènman sa a",
    "register_participant": "Enskri", "outcome_registered": "Enskri", "outcome_waitlisted": "Evènman an plen : lis datant",
    "outcome_already": "Deja enskri", "consent_required": "Konsantman obligatwa",
    "stats_line": "Enskri : {registered} · Ap tann : {waitlisted} · Prezans : {checked}", "you": "Ou menm"})
STRINGS["en"].update({
    "language": "Language", "new_church": "New church", "church_name": "Official church name",
    "department": "Department", "commune": "Commune", "save": "Save", "events": "Events",
    "invalid_form": "Name, department and commune are required",
    "saved_sent": "Church saved on the server", "saved_local": "Saved on this device: will be sent as soon as possible",
    "rejected_ops": "Rejected", "sent_count": "Sent", "rejected_count": "Rejected", "nothing_pending": "Nothing to send",
    "vs_draft": "draft", "vs_pending": "awaiting validation", "vs_approved": "approved", "vs_published": "published",
    "vs_withdrawn": "withdrawn", "vs_archived": "archived",
    "st_organized": "filed", "st_needs_review": "needs review", "st_duplicate": "already present", "st_error": "error",
    "js_pending": "waiting", "js_accepted": "accepted", "js_in_progress": "printing", "js_completed": "done",
    "js_transmitted": "sent (completion can't be confirmed)", "js_error": "error", "js_cancelled": "cancelled",
    "event": "Event", "no_events": "No events", "participant_name": "Full name", "participant_email": "Email",
    "participant_phone": "Phone", "consent_label": "The person agrees to the use of their data for this event",
    "register_participant": "Register", "outcome_registered": "Registered", "outcome_waitlisted": "Event full: waiting list",
    "outcome_already": "Already registered", "consent_required": "Consent is required",
    "stats_line": "Registered: {registered} · Waiting: {waitlisted} · Checked in: {checked}", "you": "You"})

# ---- v0.9 : registre MEOL (organisations affiliées) importé depuis les listes ----
STRINGS["fr"].update({
    "meol": "Registre MEOL", "meol_hint": "Chercher un nom", "meol_all": "Tous les départements",
    "meol_none": "Aucun MEOL trouvé", "meol_total": "Fiches", "search": "Rechercher",
    "meol_prev": "Précédent", "meol_next": "Suivant", "meol_page": "page",
    "meol_draft_note": "Import du registre : rien n'est publié sans validation",
    "ot_ministere": "Ministère", "ot_association": "Association", "ot_ecole": "École",
    "ot_oeuvre_sociale": "Œuvre sociale", "ot_autre": "Autre"})
STRINGS["ht"].update({
    "meol": "Rejis MEOL", "meol_hint": "Chèche yon non", "meol_all": "Tout depatman",
    "meol_none": "Pa gen MEOL jwenn", "meol_total": "Fich", "search": "Chèche",
    "meol_prev": "Presedan", "meol_next": "Swivan", "meol_page": "paj",
    "meol_draft_note": "Import rejis la : anyen pibliye san validasyon",
    "ot_ministere": "Minis", "ot_association": "Asosyasyon", "ot_ecole": "Lekòl",
    "ot_oeuvre_sociale": "Zèv sosyal", "ot_autre": "Lot"})
STRINGS["en"].update({
    "meol": "MEOL register", "meol_hint": "Search a name", "meol_all": "All departments",
    "meol_none": "No MEOL found", "meol_total": "Records", "search": "Search",
    "meol_prev": "Previous", "meol_next": "Next", "meol_page": "page",
    "meol_draft_note": "Registry import: nothing is published without validation",
    "ot_ministere": "Ministry", "ot_association": "Association", "ot_ecole": "School",
    "ot_oeuvre_sociale": "Social work", "ot_autre": "Other"})
