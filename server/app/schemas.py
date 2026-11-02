from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from .permissions import DEPARTMENTS


class LoginIn(BaseModel):
    """`identifier` = e-mail OU pseudo. `email` reste accepté (compatibilité)."""
    identifier: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    password: str = Field(max_length=200)
    device_label: str | None = Field(default=None, max_length=120)

    @property
    def login_id(self) -> str:
        return (self.identifier or self.email or "").strip().lower()


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime


class UserOut(BaseModel):
    id: str
    email: str
    username: str | None = None
    must_change_password: bool = False
    full_name: str
    role: str
    department: str | None
    church_id: str | None
    organization_id: str | None = None
    is_active: bool
    permissions: list[str]


class UserCreate(BaseModel):
    username: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._-]{3,50}$")
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=200)
    password: str
    role_code: str
    department: str | None = None
    church_id: str | None = None
    organization_id: str | None = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


class ChurchBase(BaseModel):
    official_name: str = Field(min_length=2, max_length=250)
    address: str | None = Field(default=None, max_length=1000)
    department: str
    commune: str = Field(min_length=2, max_length=100)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    contact_email: EmailStr | None = None
    contact_phone: str | None = Field(default=None, max_length=50)
    main_leader_name: str | None = Field(default=None, max_length=200)

    @field_validator("department")
    @classmethod
    def _dept(cls, v):
        if v not in DEPARTMENTS:
            raise ValueError(f"Département inconnu. Valeurs : {', '.join(DEPARTMENTS)}")
        return v


class ChurchCreate(ChurchBase):
    affiliation_status: str = Field(default="pending", pattern="^(pending|affiliated|suspended)$")


class ChurchUpdate(BaseModel):
    version: int = Field(description="Version lue par le client (détection de conflit)")
    official_name: str | None = Field(default=None, min_length=2, max_length=250)
    address: str | None = None
    department: str | None = None
    commune: str | None = Field(default=None, min_length=2, max_length=100)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    contact_email: EmailStr | None = None
    contact_phone: str | None = None
    main_leader_name: str | None = None
    affiliation_status: str | None = Field(default=None, pattern="^(pending|affiliated|suspended)$")

    @field_validator("department")
    @classmethod
    def _dept(cls, v):
        if v is not None and v not in DEPARTMENTS:
            raise ValueError("Département inconnu")
        return v


class ChurchOut(ChurchBase):
    model_config = {"from_attributes": True}
    id: str
    validation_status: str
    affiliation_status: str
    version: int
    created_at: datetime
    updated_at: datetime


class ChurchPublicOut(BaseModel):
    """Champs publics uniquement : pas d'e-mail ni de nom de responsable."""
    model_config = {"from_attributes": True}
    id: str
    official_name: str
    address: str | None
    department: str
    commune: str
    latitude: float | None
    longitude: float | None
    contact_phone: str | None


class TransitionIn(BaseModel):
    action: str = Field(pattern="^(submit|approve|reject|publish|withdraw|archive)$")


class HistoryOut(BaseModel):
    model_config = {"from_attributes": True}
    version: int
    action: str
    changes: dict
    actor_id: str | None
    at: datetime
