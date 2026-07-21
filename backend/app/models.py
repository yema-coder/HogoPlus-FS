import uuid
from datetime import date, datetime, time

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
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


class FactorySettings(TimestampMixin, Base):
    __tablename__ = "settings"
    id: Mapped[uuid.UUID] = uuid_pk()
    factory_lat: Mapped[float] = mapped_column(Float, nullable=False)
    factory_lng: Mapped[float] = mapped_column(Float, nullable=False)
    radius_meters: Mapped[int] = mapped_column(Integer, nullable=False)


class BleBeacon(TimestampMixin, Base):
    __tablename__ = "ble_beacons"
    id: Mapped[uuid.UUID] = uuid_pk()
    beacon_uuid: Mapped[str] = mapped_column(String(100), nullable=False)
    # vendor beacons are MAC-based (non-configurable) — matching happens on this field
    mac_address: Mapped[str | None] = mapped_column(String(17), nullable=True, unique=True)
    major: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
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
