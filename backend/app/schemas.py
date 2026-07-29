"""Pydantic v2 request models."""
import datetime as _datetime
import re
import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

PHONE_REGEX = r"^\+91[6-9]\d{9}$"
MAC_REGEX = r"^[0-9A-F]{2}(:[0-9A-F]{2}){5}$"
UUID_REGEX = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"


def normalize_mac(v: str | None) -> str | None:
    """Uppercase + validate AA:BB:CC:DD:EE:FF format."""
    if v is None:
        return None
    v = v.strip().upper()
    if not re.fullmatch(MAC_REGEX, v):
        raise ValueError("mac_address must be in AA:BB:CC:DD:EE:FF format")
    return v


def normalize_beacon_uuid(v: str | None) -> str | None:
    """Lowercase + validate the standard 8-4-4-4-12 iBeacon UUID. Empty → None."""
    if v is None:
        return None
    v = v.strip().lower()
    if v == "":
        return None
    if not re.fullmatch(UUID_REGEX, v):
        raise ValueError("ibeacon uuid must be standard 8-4-4-4-12 hex format")
    return v


class SendOtpIn(BaseModel):
    phone: str = Field(pattern=PHONE_REGEX)


class TestSmsIn(BaseModel):
    phone: str = Field(pattern=PHONE_REGEX)


class VerifyOtpIn(BaseModel):
    phone: str = Field(pattern=PHONE_REGEX)
    otp: str = Field(min_length=4, max_length=8)


class RegisterIn(BaseModel):
    phone: str = Field(pattern=PHONE_REGEX)
    full_name: str = Field(min_length=2, max_length=200)
    selfie_key: str = Field(min_length=1)


class ApproveRegistrationIn(BaseModel):
    department_code: str
    role_code: str = "Worker"
    emp_id: str = Field(min_length=1, max_length=20)


class ConfirmRoutingIn(BaseModel):
    """Empty body = accept the AI suggestion as-is."""
    category: str | None = None
    department_code: str | None = None
    severity: str | None = None


class PasswordLoginIn(BaseModel):
    emp_id: str = Field(min_length=1, max_length=20)
    password: str = Field(min_length=1, max_length=128)


class SetPasswordIn(BaseModel):
    password: str = Field(min_length=8, max_length=128)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class RefreshIn(BaseModel):
    refresh_token: str


class UpdateMeIn(BaseModel):
    language_pref: str | None = None
    expo_push_token: str | None = None

    @field_validator("language_pref")
    @classmethod
    def _lang(cls, v):
        if v is not None and v not in ("en", "hi", "mr"):
            raise ValueError("language_pref must be en/hi/mr")
        return v


class TokenPairOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class FormSubmitIn(BaseModel):
    data_json: dict
    photos: list[str] = Field(default_factory=list)
    gps_lat: float | None = None
    gps_lng: float | None = None
    address_text: str | None = Field(default=None, max_length=300)


class RejectIn(BaseModel):
    reason: str = Field(min_length=1)


class FormDefCreateIn(BaseModel):
    department_code: str
    code: str = Field(min_length=2, max_length=50)
    title_en: str
    title_hi: str
    title_mr: str
    schema_json: dict
    requires_approval: bool = True
    approval_role_code: str = "Manager"


class FormDefPatchIn(BaseModel):
    title_en: str | None = None
    title_hi: str | None = None
    title_mr: str | None = None
    schema_json: dict | None = None
    is_active: bool | None = None
    requires_approval: bool | None = None
    approval_role_code: str | None = None


class IncidentCreateIn(BaseModel):
    category: str
    department_code: str
    photo_key: str | None = None
    video_key: str | None = None
    gps_lat: float | None = None
    gps_lng: float | None = None
    address_text: str | None = Field(default=None, max_length=300)
    description: str | None = None
    voice_note_key: str | None = None
    severity: str = "normal"
    # BLE zone CONTEXT (non-blocking, background scan at capture; may be null).
    ble_beacon_id: str | None = None
    ble_ibeacon_uuid: str | None = None
    ble_ibeacon_major: int | None = None
    ble_ibeacon_minor: int | None = None

    @model_validator(mode="after")
    def _media_required(self):
        if not self.photo_key and not self.video_key:
            raise ValueError("photo_key or video_key is required")
        return self

    @field_validator("category")
    @classmethod
    def _cat(cls, v):
        allowed = {"safety", "fire", "machine_breakdown", "injury", "electrical", "water_leakage", "security", "other"}
        if v not in allowed:
            raise ValueError(f"category must be one of {sorted(allowed)}")
        return v

    @field_validator("severity")
    @classmethod
    def _sev(cls, v):
        if v not in ("normal", "high", "critical"):
            raise ValueError("severity must be normal/high/critical")
        return v


class IncidentStatusIn(BaseModel):
    status: str
    note: str | None = None
    resolution_photo_key: str | None = None

    @field_validator("status")
    @classmethod
    def _st(cls, v):
        if v not in ("seen", "in_progress", "resolved"):
            raise ValueError("status must be seen/in_progress/resolved")
        return v


class PunchInIn(BaseModel):
    gps_lat: float | None = None
    gps_lng: float | None = None
    selfie_key: str = Field(min_length=1)
    # Dual-mode BLE: the app sends whichever identifier matched a registered beacon.
    # MAC of the strongest matched beacon (MAC mode)...
    ble_beacon_id: str | None = None
    # ...OR the iBeacon triple (UUID/Major/Minor mode). Backend resolves the zone.
    ble_ibeacon_uuid: str | None = None
    ble_ibeacon_major: int | None = None
    ble_ibeacon_minor: int | None = None


class SwapCreateIn(BaseModel):
    target_employee_id: uuid.UUID
    swap_date: date
    reason: str | None = None


class SwapRespondIn(BaseModel):
    accept: bool


class SwapDecideIn(BaseModel):
    approve: bool
    reason: str | None = None


class BleDiagIn(BaseModel):
    """v1.0.16 field instrumentation: free-form BLE diagnostic report from the app."""

    report: dict


class SettingsPatchIn(BaseModel):
    factory_lat: float | None = None
    factory_lng: float | None = None
    radius_meters: int | None = Field(default=None, ge=50, le=10000)
    beacon_first_mode: bool | None = None


class EmployeePatchIn(BaseModel):
    phone: str | None = Field(default=None, pattern=PHONE_REGEX)
    full_name: str | None = None
    role_code: str | None = None
    department_code: str | None = None
    shift_code: str | None = None
    is_active: bool | None = None


class AssignManagerIn(BaseModel):
    employee_id: uuid.UUID


class BeaconIn(BaseModel):
    # Dual-mode: register EITHER a MAC address OR a full iBeacon (UUID+Major+Minor).
    beacon_uuid: str | None = None
    major: int | None = Field(default=None, ge=0, le=65535)
    minor: int | None = Field(default=None, ge=0, le=65535)
    mac_address: str | None = None
    zone_label_en: str
    zone_label_hi: str
    zone_label_mr: str
    department_code: str | None = None
    is_active: bool = True

    @field_validator("mac_address")
    @classmethod
    def _mac(cls, v):
        return normalize_mac(v)

    @field_validator("beacon_uuid")
    @classmethod
    def _uuid(cls, v):
        return normalize_beacon_uuid(v)

    @model_validator(mode="after")
    def _identifier_required(self):
        has_mac = self.mac_address is not None
        has_ibeacon = self.beacon_uuid is not None and self.major is not None and self.minor is not None
        if not has_mac and not has_ibeacon:
            raise ValueError(
                "Provide either mac_address OR all of beacon_uuid + major + minor"
            )
        return self


class BeaconPatchIn(BaseModel):
    beacon_uuid: str | None = None
    major: int | None = Field(default=None, ge=0, le=65535)
    minor: int | None = Field(default=None, ge=0, le=65535)
    mac_address: str | None = None
    zone_label_en: str | None = None
    zone_label_hi: str | None = None
    zone_label_mr: str | None = None
    department_code: str | None = None
    is_active: bool | None = None

    @field_validator("mac_address")
    @classmethod
    def _mac(cls, v):
        return normalize_mac(v)

    @field_validator("beacon_uuid")
    @classmethod
    def _uuid(cls, v):
        return normalize_beacon_uuid(v)


class BeaconBulkRow(BaseModel):
    minor: int = Field(ge=0, le=65535)
    zone_name: str = Field(min_length=1, max_length=100)


class BeaconBulkIn(BaseModel):
    """Register all units at once: one shared UUID + Major, many (minor, zone_name) rows."""
    beacon_uuid: str
    major: int = Field(ge=0, le=65535)
    department_code: str | None = None
    rows: list[BeaconBulkRow] = Field(min_length=1, max_length=500)

    @field_validator("beacon_uuid")
    @classmethod
    def _uuid(cls, v):
        out = normalize_beacon_uuid(v)
        if out is None:
            raise ValueError("beacon_uuid is required for bulk import")
        return out


# ---------------- Phase 4: AI ----------------

class AnprIn(BaseModel):
    photo_key: str = Field(min_length=1, max_length=500)


class GaugeReadIn(BaseModel):
    photo_key: str = Field(min_length=1, max_length=500)
    expected_min: float | None = None
    expected_max: float | None = None


class VoiceFillIn(BaseModel):
    audio_key: str = Field(min_length=1, max_length=500)
    form_definition_id: uuid.UUID


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    conversation_id: uuid.UUID | None = None


class GenerateReportIn(BaseModel):
    date: _datetime.date | None = None


class PurgeDemoIn(BaseModel):
    dry_run: bool = True
    include_seed: bool = False


class AppVersionIn(BaseModel):
    latest_version: str = Field(min_length=1, max_length=20)
    apk_url: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=1000)
    force_update: bool = False


class BeaconAttachIn(BaseModel):
    """v1.0.17 speed pack: attach a late-arriving beacon match to a just-created punch."""

    ble_beacon_id: str | None = Field(default=None, max_length=17)
    ble_ibeacon_uuid: str | None = Field(default=None, max_length=36)
    ble_ibeacon_major: int | None = Field(default=None, ge=0, le=65535)
    ble_ibeacon_minor: int | None = Field(default=None, ge=0, le=65535)


class DirectAddEmployeeIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    phone: str = Field(pattern=PHONE_REGEX)
    department_code: str
    role_code: str
    shift_code: str | None = None
    emp_id: str = Field(min_length=1, max_length=20)


class EscalateIn(BaseModel):
    mode: Literal["department", "employee"]
    department_code: str | None = None
    employee_id: uuid.UUID | None = None
    reason: str = Field(min_length=3, max_length=300)


class AnnouncementIn(BaseModel):
    title: str = Field(min_length=2, max_length=120)
    message: str = Field(min_length=2, max_length=1000)
    audience: Literal["all", "department"] = "department"
    department_code: str | None = None


class FaceEnrollIn(BaseModel):
    selfie_key: str = Field(min_length=1, max_length=500)
