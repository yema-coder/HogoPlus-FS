import uuid
from datetime import date, datetime, time

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

ONBOARDING_STATUS = Enum(
    "seeded", "self_registered", "pending_approval", "approved", "rejected",
    name="onboarding_status",
)
SWAP_STATUS = Enum(
    "pending_target", "pending_manager", "approved", "rejected", "cancelled",
    name="swap_status",
)
SUBMISSION_STATUS = Enum(
    "submitted", "approved", "rejected", "escalated", name="submission_status"
)
INCIDENT_CATEGORY = Enum(
    "safety", "fire", "machine_breakdown", "injury", "electrical",
    "water_leakage", "security", "other",
    name="incident_category",
)
INCIDENT_STATUS = Enum(
    "submitted", "seen", "in_progress", "resolved", "escalated", name="incident_status"
)
INCIDENT_SEVERITY = Enum("normal", "high", "critical", name="incident_severity")
VERIFICATION_LEVEL = Enum(
    "verified_plus", "verified", "flagged", name="verification_level"
)
ASSIGNMENT_SOURCE = Enum("baseline", "swap", name="assignment_source")


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


def uuid_pk():
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class Role(TimestampMixin, Base):
    __tablename__ = "roles"
    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    label_en: Mapped[str] = mapped_column(String(100), nullable=False)
    label_hi: Mapped[str] = mapped_column(String(100), nullable=False)
    label_mr: Mapped[str] = mapped_column(String(100), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)


class Department(TimestampMixin, Base):
    __tablename__ = "departments"
    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    name_en: Mapped[str] = mapped_column(String(100), nullable=False)
    name_hi: Mapped[str] = mapped_column(String(100), nullable=False)
    name_mr: Mapped[str] = mapped_column(String(100), nullable=False)
    manager_employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", use_alter=True, name="fk_departments_manager"),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # v1.0.24 per-department policy flags (general capability, not hardcoded to a
    # dept). HEAD_OFFICE (Pune, remote, no beacons) ships with all three ON.
    # beacon_exempt: punches never wait for/require/flag on beacons (incl. beacon-first mode)
    beacon_exempt: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    # geofence_exempt: the factory geofence never flags this department's punches
    # (GPS still captured + stored as evidence; gps_missing still flags)
    geofence_exempt: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    # can_add_employees: managers of this department get the direct-add capability
    can_add_employees: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )


class Employee(TimestampMixin, Base):
    __tablename__ = "employees"
    id: Mapped[uuid.UUID] = uuid_pk()
    emp_id: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    department_code: Mapped[str | None] = mapped_column(
        String(30), ForeignKey("departments.code"), nullable=True
    )
    designation: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    role_code: Mapped[str] = mapped_column(String(20), ForeignKey("roles.code"), nullable=False)
    language_pref: Mapped[str] = mapped_column(String(5), default="mr", nullable=False)
    shift_swap_eligible: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    onboarding_status: Mapped[str] = mapped_column(
        ONBOARDING_STATUS, default="approved", nullable=False
    )
    selfie_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    reference_selfie_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # registration evidence (v1.0.20): captured once at self-registration
    reg_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    reg_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    reg_address: Mapped[str | None] = mapped_column(String(300), nullable=True)
    reg_zone: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reg_inside_geofence: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    reg_device: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reg_app_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    reg_face_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reference_selfie_set_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expo_push_token: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Prompt 14: demo showcase account — all created records inherit is_demo=true
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False, index=True)

    role: Mapped["Role"] = relationship(
        "Role", primaryjoin="Employee.role_code == Role.code",
        foreign_keys=[role_code], lazy="joined", viewonly=True,
    )
    department: Mapped["Department"] = relationship(
        "Department", primaryjoin="Employee.department_code == Department.code",
        foreign_keys=[department_code], lazy="joined", viewonly=True,
    )


class Shift(TimestampMixin, Base):
    __tablename__ = "shifts"
    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(String(10), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(50), nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)


class ShiftAssignment(TimestampMixin, Base):
    __tablename__ = "shift_assignments"
    __table_args__ = (
        UniqueConstraint("employee_id", "effective_date", "source", name="uq_shift_assignment"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False, index=True
    )
    shift_code: Mapped[str] = mapped_column(String(10), ForeignKey("shifts.code"), nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(ASSIGNMENT_SOURCE, default="baseline", nullable=False)


class ShiftSwapRequest(TimestampMixin, Base):
    __tablename__ = "shift_swap_requests"
    id: Mapped[uuid.UUID] = uuid_pk()
    requester_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False
    )
    target_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False
    )
    swap_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(SWAP_STATUS, default="pending_target", nullable=False)
    target_responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    manager_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=True
    )
    manager_responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False, index=True)
    is_demo_seed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)


class FormDefinition(TimestampMixin, Base):
    __tablename__ = "form_definitions"
    __table_args__ = (UniqueConstraint("department_code", "code", name="uq_form_dept_code"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    department_code: Mapped[str] = mapped_column(
        String(30), ForeignKey("departments.code"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    title_en: Mapped[str] = mapped_column(String(200), nullable=False)
    title_hi: Mapped[str] = mapped_column(String(200), nullable=False)
    title_mr: Mapped[str] = mapped_column(String(200), nullable=False)
    schema_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    approval_role_code: Mapped[str] = mapped_column(String(20), default="Manager", nullable=False)


class FormSubmission(TimestampMixin, Base):
    __tablename__ = "form_submissions"
    id: Mapped[uuid.UUID] = uuid_pk()
    form_definition_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("form_definitions.id"), nullable=False
    )
    form_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    # offline outbox idempotency: same client_uuid replayed → same row back
    client_uuid: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    submitted_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False
    )
    department_code: Mapped[str] = mapped_column(
        String(30), ForeignKey("departments.code"), nullable=False
    )
    data_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    photos: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    detected_plates: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    address_text: Mapped[str | None] = mapped_column(String(300), nullable=True)
    gps_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    gps_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(SUBMISSION_STATUS, default="submitted", nullable=False)
    approver_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    escalated_to: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=True
    )
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False, index=True)
    is_demo_seed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)


class Incident(TimestampMixin, Base):
    __tablename__ = "incidents"
    id: Mapped[uuid.UUID] = uuid_pk()
    reported_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False
    )
    department_code: Mapped[str] = mapped_column(
        String(30), ForeignKey("departments.code"), nullable=False
    )
    category: Mapped[str] = mapped_column(INCIDENT_CATEGORY, nullable=False)
    photo_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    video_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # offline outbox idempotency: same client_uuid replayed → same row back
    client_uuid: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    gps_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    gps_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    address_text: Mapped[str | None] = mapped_column(String(300), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    voice_note_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(INCIDENT_STATUS, default="submitted", nullable=False)
    severity: Mapped[str] = mapped_column(INCIDENT_SEVERITY, default="normal", nullable=False)
    severity_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    assigned_manager_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=True
    )
    escalated_to: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=True
    )
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolution_photo_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    severity_reason_mr: Mapped[str | None] = mapped_column(String(300), nullable=True)
    ai_suggested_category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ai_suggested_department: Mapped[str | None] = mapped_column(String(30), nullable=True)
    ai_suggested_severity: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ai_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_confirmed_by: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ai_suggested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    detected_plate: Mapped[str | None] = mapped_column(String(20), nullable=True)
    plate_status: Mapped[str | None] = mapped_column(String(20), nullable=True)  # pending|detected|not_detected
    plate_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0-100
    plate_source: Mapped[str | None] = mapped_column(String(20), nullable=True)  # rekognition|llm_vision
    plate_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)  # code when not_detected
    # AR object distance measured on-device at the instant of capture (Step 3).
    # distance_method: lidar|depth|ar_plane|ar_point|feature|none ; confidence: high|medium|low
    distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    distance_confidence: Mapped[str | None] = mapped_column(String(10), nullable=True)
    distance_uncertainty_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    # BLE dual-mode zone CONTEXT (not verification): identifier the app matched at
    # capture time (MAC or "ibeacon:<uuid>:<major>:<minor>") + resolved zone label.
    ble_beacon_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ble_zone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # v1.0.21 duplicate clustering (DISPLAY-ONLY): points to the cluster root
    # incident. Both records survive intact — reporters keep their own status,
    # credit and notifications; only manager CARDS are grouped.
    duplicate_of: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incidents.id"), nullable=True, index=True
    )
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False, index=True)
    is_demo_seed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)


class IncidentTimeline(Base):
    __tablename__ = "incident_timeline"
    id: Mapped[uuid.UUID] = uuid_pk()
    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incidents.id"), nullable=False, index=True
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=True
    )
    event: Mapped[str] = mapped_column(String(30), nullable=False)
    detail_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Attendance(TimestampMixin, Base):
    __tablename__ = "attendance"
    __table_args__ = (UniqueConstraint("employee_id", "date", name="uq_attendance_emp_date"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False, index=True
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    punch_in_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    punch_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    gps_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    gps_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    gps_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ble_beacon_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ble_zone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    selfie_key: Mapped[str] = mapped_column(String(500), nullable=False)
    verification_level: Mapped[str] = mapped_column(VERIFICATION_LEVEL, nullable=False)
    shift_code: Mapped[str | None] = mapped_column(
        String(10), ForeignKey("shifts.code"), nullable=True
    )
    is_late: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    flagged_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    face_match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    face_verified: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=True
    )
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False, index=True)
    is_demo_seed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)


class AttendanceRegularization(TimestampMixin, Base):
    """v1.0.21: one-tap "this punch is wrong" dispute on a flagged punch.
    ONE open request per punch (partial unique index — no spam); the TO decides
    with the original punch evidence alongside; decision is audited with the
    reviewer's name and notifies the worker."""

    __tablename__ = "attendance_regularizations"
    __table_args__ = (
        Index(
            "uq_att_reg_open", "attendance_id",
            unique=True, postgresql_where=text("status = 'open'"),
        ),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    attendance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("attendance.id"), nullable=False, index=True
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False, index=True
    )
    text_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    voice_note_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)  # open|approved|rejected
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False, index=True)


class FactorySettings(TimestampMixin, Base):
    __tablename__ = "settings"
    id: Mapped[uuid.UUID] = uuid_pk()
    factory_lat: Mapped[float] = mapped_column(Float, nullable=False)
    factory_lng: Mapped[float] = mapped_column(Float, nullable=False)
    radius_meters: Mapped[int] = mapped_column(Integer, nullable=False)
    # Beacon-first policy flag (Task B, ships OFF): beacon zone is the primary
    # location identity; GPS/geofence become secondary evidence and never decide
    # the punch outcome. OFF = launch BEACON-WINS ladder, byte-identical.
    beacon_first_mode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # v1.0.21 duplicate-incident clustering rules — tunable WITHOUT a deploy
    # (PATCH /api/admin/settings). Display-only grouping; records never merge.
    dup_window_minutes: Mapped[int] = mapped_column(
        Integer, default=30, server_default="30", nullable=False
    )
    dup_same_zone: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    dup_same_category: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    # Wave-1 dept upgrade flags (all default OFF; demo bubble bypasses them)
    home_config_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    vehicle_log_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    notif_batching_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    # v1.0.24 MD access redesign: ONE shared dashboard password (no emp_id) and
    # the exact OTP numbers allowed to reach the MD dashboard (comma-separated
    # +91XXXXXXXXXX). Managed by scripts/seed_head_office_md.py + POST /admin/md-password.
    md_password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    md_otp_phones: Mapped[str] = mapped_column(
        String(200), default="", server_default="", nullable=False
    )
    # v1.0.25 LIVE WORKER PRESENCE (Phase 1) — everything OFF by default.
    # A worker is tracked ONLY when: global flag ON + emp_id in the pilot list
    # + consent recorded + currently punched in. Both gates required (owner rule 6).
    live_presence_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    presence_pilot_emp_ids: Mapped[str] = mapped_column(
        Text, default="", server_default="", nullable=False
    )  # comma-separated emp_ids
    presence_nosignal_alert_min: Mapped[int] = mapped_column(
        Integer, default=15, server_default="15", nullable=False
    )
    presence_outside_alert_min: Mapped[int] = mapped_column(
        Integer, default=10, server_default="10", nullable=False
    )
    # v1.0.27 Broadcast / Send-Notification engine — flag OFF by default until
    # the owner approves. When OFF, only preview + "send test to me" work; real
    # send/schedule is blocked server-side.
    broadcasts_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    broadcast_rate_per_hour: Mapped[int] = mapped_column(
        Integer, default=10, server_default="10", nullable=False
    )
    # Step 3 camera AI feature flags (default ON — the owner may toggle OFF to save
    # compute). ar_distance_enabled gates the on-device distance overlay; the other
    # two gate the backend face / number-plate analysis of captured photos.
    ar_distance_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    face_detection_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    plate_detection_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    # Step 5 plate-scale cross-check: an independent distance estimate from the
    # apparent width of a standard number plate. k ≈ focal_length_px / image_width_px
    # (resolution-independent); distance ≈ k · ref_width_m / plate_width_fraction.
    plate_scale_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    plate_ref_width_m: Mapped[float] = mapped_column(
        Float, default=0.5, server_default="0.5", nullable=False
    )
    plate_scale_k: Mapped[float] = mapped_column(
        Float, default=1.2, server_default="1.2", nullable=False
    )


class BleBeacon(TimestampMixin, Base):
    __tablename__ = "ble_beacons"
    __table_args__ = (
        # dual-mode: same iBeacon (UUID, Major, Minor) can't map to two zones.
        # MAC-only rows leave all three NULL (NULLs are distinct in Postgres).
        UniqueConstraint("beacon_uuid", "major", "minor", name="uq_ble_beacons_ibeacon"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    beacon_uuid: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # vendor beacons are MAC-based (non-configurable) — matching happens on this field
    mac_address: Mapped[str | None] = mapped_column(String(17), nullable=True, unique=True)
    major: Mapped[int | None] = mapped_column(Integer, nullable=True)
    minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    zone_label_en: Mapped[str] = mapped_column(String(100), nullable=False)
    zone_label_hi: Mapped[str] = mapped_column(String(100), nullable=False)
    zone_label_mr: Mapped[str] = mapped_column(String(100), nullable=False)
    department_code: Mapped[str | None] = mapped_column(
        String(30), ForeignKey("departments.code"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[uuid.UUID] = uuid_pk()
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    detail_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False, index=True)
    is_demo_seed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)


class OtpAttempt(Base):
    __tablename__ = "otp_attempts"
    id: Mapped[uuid.UUID] = uuid_pk()
    phone: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    purpose: Mapped[str] = mapped_column(String(30), nullable=False, default="login")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[uuid.UUID] = uuid_pk()
    recipient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(String(40), nullable=False)
    title_en: Mapped[str] = mapped_column(String(200), nullable=False)
    title_hi: Mapped[str] = mapped_column(String(200), nullable=False)
    title_mr: Mapped[str] = mapped_column(String(200), nullable=False)
    body_en: Mapped[str] = mapped_column(Text, nullable=False, default="")
    body_hi: Mapped[str] = mapped_column(Text, nullable=False, default="")
    body_mr: Mapped[str] = mapped_column(Text, nullable=False, default="")
    entity_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False, index=True)
    is_demo_seed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)


class AppVersion(TimestampMixin, Base):
    """Single-row table driving the mobile 'update available' banner (Prompt 16)."""

    __tablename__ = "app_versions"
    id: Mapped[uuid.UUID] = uuid_pk()
    latest_version: Mapped[str] = mapped_column(String(20), nullable=False)
    apk_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # v1.0.17: when True the Play in-app update runs IMMEDIATE (blocking) instead of flexible
    force_update: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class SopDoc(TimestampMixin, Base):
    __tablename__ = "sop_docs"
    id: Mapped[uuid.UUID] = uuid_pk()
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    file_key: Mapped[str] = mapped_column(String(500), nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False
    )


class SopChunk(Base):
    __tablename__ = "sop_chunks"
    id: Mapped[uuid.UUID] = uuid_pk()
    doc_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sop_docs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding = mapped_column(Vector(384), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id: Mapped[uuid.UUID] = uuid_pk()
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False, index=True
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(10), nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False, index=True)
    is_demo_seed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)


class HomeConfig(TimestampMixin, Base):
    """Per-department/role home screen layout. Resolution order in the API:
    (dept, role) > (dept, NULL) > (NULL, role) > None (app renders its built-in
    fallback home). Changing a department's home after Wave 1 is a config edit
    here — never an APK."""

    __tablename__ = "home_configs"
    __table_args__ = (
        UniqueConstraint("department_code", "role_code", name="uq_home_config_dept_role"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    department_code: Mapped[str | None] = mapped_column(
        String(30), ForeignKey("departments.code"), nullable=True
    )
    role_code: Mapped[str | None] = mapped_column(String(20), ForeignKey("roles.code"), nullable=True)
    config_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)


class VehicleLog(TimestampMixin, Base):
    """Security gate register: one row per vehicle movement (IN or OUT). An OUT
    row is paired to its latest unpaired IN row (same plate, same demo class) —
    both sides get paired_log_id so 'currently inside' = IN rows with NULL pair."""

    __tablename__ = "vehicle_logs"
    id: Mapped[uuid.UUID] = uuid_pk()
    plate: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    vehicle_type: Mapped[str] = mapped_column(String(20), nullable=False)
    direction: Mapped[str] = mapped_column(String(3), nullable=False)  # in | out
    driver_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    purpose: Mapped[str | None] = mapped_column(String(100), nullable=True)
    photo_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    voice_note_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    gate_zone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    anpr_used: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    logged_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False
    )
    paired_log_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vehicle_logs.id"), nullable=True
    )
    client_uuid: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    is_demo: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False, index=True
    )
    logged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# ---------------- v1.0.25 LIVE WORKER PRESENCE (Phase 1) ----------------

class WorkerPresence(TimestampMixin, Base):
    """LATEST known state per worker — one row, upserted on every accepted ping.
    Freshness is ALWAYS computed off server_ts (cheap phones have clock drift);
    stale data is shown as history, never as live."""

    __tablename__ = "worker_presence"
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), primary_key=True
    )
    source: Mapped[str] = mapped_column(String(10), nullable=False)  # beacon | gps | stopped
    zone_key: Mapped[str | None] = mapped_column(String(150), nullable=True)
    zone_en: Mapped[str | None] = mapped_column(String(100), nullable=True)
    zone_hi: Mapped[str | None] = mapped_column(String(100), nullable=True)
    zone_mr: Mapped[str | None] = mapped_column(String(100), nullable=True)
    zone_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    accuracy_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    inside_geofence: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    battery_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    app_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    client_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    server_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    is_demo: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False, index=True
    )


class PresenceHistory(Base):
    """Append-only trail for replay/timeline. Auto-purged after 30 days."""

    __tablename__ = "presence_history"
    id: Mapped[uuid.UUID] = uuid_pk()
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False, index=True
    )
    source: Mapped[str] = mapped_column(String(10), nullable=False)
    zone_key: Mapped[str | None] = mapped_column(String(150), nullable=True)
    zone_en: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    accuracy_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    inside_geofence: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    battery_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    client_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    server_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    is_demo: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False, index=True
    )


class PresenceAlert(TimestampMixin, Base):
    """v1.0.26 Phase 2 alerts engine — ONE open row per (employee, alert_type).
    The minute-sweep raises / refreshes (last_seen_at) / auto-resolves; managers
    acknowledge or resolve manually. resolved_by NULL + resolved = auto-cleared."""

    __tablename__ = "presence_alerts"
    id: Mapped[uuid.UUID] = uuid_pk()
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False, index=True
    )
    alert_type: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # outside_geofence | gone_dark | low_battery | unauthorized_zone
    status: Mapped[str] = mapped_column(
        String(15), default="active", server_default="active", nullable=False, index=True
    )  # active | acknowledged | resolved
    zone_key: Mapped[str | None] = mapped_column(String(150), nullable=True)
    zone_en: Mapped[str | None] = mapped_column(String(100), nullable=True)
    detail: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=True
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_demo: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False, index=True
    )


class PresenceConsent(TimestampMixin, Base):
    """Versioned, server-side consent record (DPDP). Tracking NEVER starts
    without a consent row matching the current consent version."""

    __tablename__ = "presence_consents"
    id: Mapped[uuid.UUID] = uuid_pk()
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False, index=True
    )
    version: Mapped[str] = mapped_column(String(10), nullable=False)
    lang: Mapped[str] = mapped_column(String(5), nullable=False, default="mr")
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# ---------------- v1.0.27 BROADCAST / SEND-NOTIFICATION ENGINE ----------------

class Broadcast(TimestampMixin, Base):
    """One composed notification push to a resolved audience. The in-app inbox
    (notifications table) is ALWAYS the source of truth — every recipient gets a
    row regardless of push state. Delivery numbers live on this row (rolled up
    from broadcast_receipts) so the history list is a single fast read."""

    __tablename__ = "broadcasts"
    id: Mapped[uuid.UUID] = uuid_pk()
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False, index=True
    )
    # all | department | role | designation | zone | employees
    audience_type: Mapped[str] = mapped_column(String(20), nullable=False)
    audience_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    title_en: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    title_hi: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    title_mr: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    body_en: Mapped[str] = mapped_column(Text, default="", nullable=False)
    body_hi: Mapped[str] = mapped_column(Text, default="", nullable=False)
    body_mr: Mapped[str] = mapped_column(Text, default="", nullable=False)
    priority: Mapped[str] = mapped_column(String(12), default="normal", nullable=False)  # normal|important|emergency
    deep_link_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    deep_link_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # scheduled | sending | sent | failed | canceled
    status: Mapped[str] = mapped_column(String(15), default="sent", nullable=False, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recipient_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    installed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sent_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    delivered_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    no_token_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    suppressed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    opened_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_test: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False, index=True)


class BroadcastReceipt(Base):
    """Per-recipient delivery tracking (drives the delivery report + resend-to-failed
    + Expo receipt polling + invalid-token cleanup)."""

    __tablename__ = "broadcast_receipts"
    id: Mapped[uuid.UUID] = uuid_pk()
    broadcast_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("broadcasts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False, index=True
    )
    notification_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    ticket_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # queued | sent | delivered | failed | no_token | suppressed | opened
    status: Mapped[str] = mapped_column(String(15), default="queued", nullable=False, index=True)
    error: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )



class PhotoAnalysis(Base):
    """One analysed photo (Step 3). Owns the face + plate detections for a single
    image attached to an incident (and, later, a form submission). Idempotent per
    (source, photo_key): the background task skips keys already marked done."""

    __tablename__ = "photo_analyses"
    id: Mapped[uuid.UUID] = uuid_pk()
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=True, index=True
    )
    submission_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("form_submissions.id", ondelete="CASCADE"), nullable=True, index=True
    )
    photo_key: Mapped[str] = mapped_column(String(500), nullable=False)
    slot: Mapped[str] = mapped_column(String(20), default="primary", nullable=False)  # primary|resolution|form
    status: Mapped[str] = mapped_column(String(15), default="pending", nullable=False)  # pending|done|failed|skipped
    face_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    plate_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False, index=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    faces: Mapped[list["PhotoFace"]] = relationship(
        "PhotoFace", cascade="all, delete-orphan", lazy="selectin"
    )
    plates: Mapped[list["PhotoPlate"]] = relationship(
        "PhotoPlate", cascade="all, delete-orphan", lazy="selectin"
    )
    __table_args__ = (
        UniqueConstraint("incident_id", "photo_key", name="uq_photo_analysis_incident_key"),
    )


class PhotoFace(Base):
    __tablename__ = "photo_faces"
    id: Mapped[uuid.UUID] = uuid_pk()
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("photo_analyses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # bounding box as fractions (0..1) of the image, origin top-left
    x: Mapped[float] = mapped_column(Float, nullable=False)
    y: Mapped[float] = mapped_column(Float, nullable=False)
    w: Mapped[float] = mapped_column(Float, nullable=False)
    h: Mapped[float] = mapped_column(Float, nullable=False)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PhotoPlate(Base):
    __tablename__ = "photo_plates"
    id: Mapped[uuid.UUID] = uuid_pk()
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("photo_analyses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    x: Mapped[float] = mapped_column(Float, nullable=False)
    y: Mapped[float] = mapped_column(Float, nullable=False)
    w: Mapped[float] = mapped_column(Float, nullable=False)
    h: Mapped[float] = mapped_column(Float, nullable=False)
    plate_text: Mapped[str | None] = mapped_column(String(20), nullable=True)
    det_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0..1 detector
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0..1 OCR mean char prob
    region: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="local_onnx", nullable=False)
    # reviewer correction: when true, plate_text was hand-edited (never auto-overwritten again)
    edited: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    edited_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id"), nullable=True
    )
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
