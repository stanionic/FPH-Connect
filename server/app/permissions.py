"""Rôles initiaux (configurables en base) et vérification de périmètre."""
from fastapi import HTTPException

LAN_STAFF = ["message:send", "device:register", "document:share", "document:read", "print:use"]
ADMIN_EXTRA = ["integration:manage", "message:broadcast", "device:manage", "document:organize", "print:manage"]
# Base institutionnelle : lecture/écriture par entité, circuit de validation partagé (organisations, événements)
FULL_INST = ["leader:read", "leader:write", "org:read", "org:write", "event:read", "event:write",
             "registration:manage", "workflow:submit", "workflow:approve", "workflow:publish",
             "workflow:archive"]
DEPT_INST = ["leader:read", "leader:write", "org:read", "org:write", "event:read", "event:write",
             "registration:manage", "workflow:submit", "workflow:approve"]
CHURCH_INST = ["leader:read", "leader:write", "org:read", "org:write", "event:read", "event:write",
               "registration:manage", "workflow:submit"]
STAFF_INST = ["event:read"]
CHURCH_ALL = ["church:read", "church:create", "church:update", "church:submit", "church:approve",
              "church:publish", "church:archive", "user:manage", "audit:read"]

ROLE_SEED = [
    ("superadmin", "Superadministrateur national", 0, CHURCH_ALL + ADMIN_EXTRA + LAN_STAFF + FULL_INST),
    ("national_admin", "Administrateur national", 10, CHURCH_ALL + ADMIN_EXTRA + LAN_STAFF + FULL_INST),
    ("dept_manager", "Responsable départemental", 20,
     ["church:read", "church:create", "church:update", "church:approve",
      "document:organize"] + LAN_STAFF + DEPT_INST),
    ("church_admin", "Administrateur d'église ou d'organisation", 30,
     ["church:read", "church:update", "church:submit"] + LAN_STAFF + CHURCH_INST),
    ("service_manager", "Responsable de service", 40, ["church:read"] + LAN_STAFF + STAFF_INST),
    ("employee", "Employé ou collaborateur", 50, ["church:read"] + LAN_STAFF + STAFF_INST),
    ("public", "Utilisateur public", 60, []),
]

ORG_TYPES = ["ministere", "ecole", "oeuvre_sociale", "association", "departement", "autre"]
LEADER_FUNCTIONS = ["pasteur_principal", "pasteur_assistant", "responsable_principal", "president",
                    "secretaire", "tresorier", "responsable_service", "autre"]

DEPARTMENTS = ["Ouest", "Nord", "Nord-Est", "Nord-Ouest", "Artibonite", "Centre",
               "Sud", "Sud-Est", "Grand'Anse", "Nippes"]

# Reprise du registre MEOL : quand aucun texte de la fiche ne désigne un département, la source dit
# « à déterminer ». L'API doit accepter cette valeur, sinon la seule façon de créer la fiche est
# d'écrire directement en base, hors du serveur — et l'enrolement continu devient impossible.
# Ce n'est aucun des dix départements : `in_scope_org` ne la montre donc à aucun responsable
# départemental, seule la relecture nationale la voit et peut la trancher.
DEPARTMENT_UNKNOWN = "À déterminer"


def has_permission(user, perm: str) -> bool:
    return user.is_active and perm in (user.role.permissions or [])


def in_scope(user, church) -> bool:
    """Périmètre : national (niveau <= 10) = tout ; départemental = son département ;
    autres = leur propre église uniquement."""
    if user.role.level <= 10:
        return True
    if user.role.code == "dept_manager":
        return user.department is not None and user.department == church.department
    return user.church_id is not None and user.church_id == church.id


def scope_filter(user):
    """Retourne (kind, value) pour filtrer une requête de liste."""
    if user.role.level <= 10:
        return ("all", None)
    if user.role.code == "dept_manager":
        return ("department", user.department)
    return ("church", user.church_id)


def forbid(detail: str = "Droits insuffisants"):
    raise HTTPException(status_code=403, detail=detail)


def in_scope_org(user, org) -> bool:
    if user.role.level <= 10:
        return True
    if user.role.code == "dept_manager":
        return user.department is not None and user.department == org.department
    return user.organization_id is not None and user.organization_id == org.id


def in_scope_event(user, ev) -> bool:
    """National : tout. Départemental : son département. Église/organisation : ses propres
    événements. Un événement sans organisateur ni département est national."""
    if user.role.level <= 10:
        return True
    if user.role.code == "dept_manager":
        return user.department is not None and user.department == ev.department
    if user.church_id and ev.organizer_church_id == user.church_id:
        return True
    return bool(user.organization_id and ev.organizer_org_id == user.organization_id)
