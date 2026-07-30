export interface RoleOut {
  code: string;
  rank: number;
  label_en: string;
  label_hi: string;
  label_mr: string;
}

export interface DepartmentRef {
  code: string;
  name_en: string;
  name_hi: string;
  name_mr: string;
}

export interface EmployeeProfile {
  id: string;
  emp_id: string;
  full_name: string;
  phone: string | null;
  department_code: string;
  department: DepartmentRef | null;
  designation: string;
  role_code: string;
  role: RoleOut | null;
  language_pref: string;
  shift_swap_eligible: boolean;
  onboarding_status: string;
  selfie_url: string | null;
  is_active: boolean;
  has_face_reference?: boolean;
}

/** v1.0.20: pending registration enriched with the evidence an approver needs. */
export interface PendingRegistration extends EmployeeProfile {
  suggested_emp_id: string;
  created_at: string | null;
  reg_lat: number | null;
  reg_lng: number | null;
  reg_address: string | null;
  reg_zone: string | null;
  reg_inside_geofence: boolean | null;
  reg_device: string | null;
  reg_app_version: string | null;
  reg_face_count: number | null;
  duplicate_hints: { emp_id: string; full_name: string; phone: string | null; similarity: number }[];
}

export interface OnboardingHistoryRow {
  action: string;
  at: string;
  by: string | null;
  detail: Record<string, unknown>;
}

export interface EscalationTarget {
  id: string;
  emp_id: string;
  full_name: string;
  department_code: string;
  role_code: string;
  role_rank: number | null;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface VerifyOtpKnown extends TokenPair {
  is_new: false;
  employee: EmployeeProfile;
}

export interface VerifyOtpNew {
  is_new: true;
  registration_token: string;
}

export type VerifyOtpResponse = VerifyOtpKnown | VerifyOtpNew;

export interface DepartmentItem {
  id: string;
  code: string;
  name_en: string;
  name_hi: string;
  name_mr: string;
  has_manager: boolean;
}

export type IncidentCategory =
  | "safety"
  | "fire"
  | "machine_breakdown"
  | "injury"
  | "electrical"
  | "water_leakage"
  | "security"
  | "other";

export type IncidentStatus = "submitted" | "seen" | "in_progress" | "resolved" | "escalated";

export interface Incident {
  id: string;
  reported_by: string;
  department_code: string;
  category: IncidentCategory;
  photo_key: string | null;
  video_key: string | null;
  video_url: string | null;
  gps_lat: number | null;
  gps_lng: number | null;
  address_text: string | null;
  ble_zone: string | null;
  ble_beacon_id: string | null;
  description: string | null;
  voice_note_key: string | null;
  status: IncidentStatus;
  severity: string;
  severity_reason: string | null;
  severity_reason_mr: string | null;
  assigned_manager_id: string | null;
  resolved_at: string | null;
  resolution_note: string | null;
  resolution_photo_key: string | null;
  resolution_photo_url: string | null;
  ai_suggested_category: string | null;
  ai_suggested_department: string | null;
  ai_suggested_severity: string | null;
  ai_confidence: number | null;
  ai_confirmed_by: string | null;
  detected_plate: string | null;
  plate_status: "pending" | "detected" | "not_detected" | null;
  plate_confidence: number | null;
  plate_source: "rekognition" | "llm_vision" | null;
  plate_reason: string | null;
  created_at: string | null;
}

export interface TimelineEntry {
  id: string;
  actor_id: string | null;
  event: string;
  detail_json: Record<string, unknown>;
  created_at: string | null;
}

export interface IncidentDetail extends Incident {
  timeline: TimelineEntry[];
}

export type VerificationLevel = "verified_plus" | "verified" | "flagged";

export interface AttendanceRecord {
  id: string;
  employee_id: string;
  date: string;
  punch_in_at: string | null;
  punch_out_at: string | null;
  gps_lat: number | null;
  gps_lng: number | null;
  gps_verified: boolean;
  ble_beacon_id: string | null;
  ble_zone: string | null;
  selfie_key: string;
  verification_level: VerificationLevel;
  shift_code: string | null;
  is_late: boolean;
  flagged_reason: string | null;
  face_match_score: number | null;
  face_verified: boolean | null;
  approved_by: string | null;
}

export interface ShiftDay {
  date: string;
  shift_code: string | null;
  label: string | null;
  start_time: string | null;
  end_time: string | null;
}

export interface NotificationItem {
  id: string;
  type: string;
  title_en: string;
  title_hi: string;
  title_mr: string;
  body_en: string;
  body_hi: string;
  body_mr: string;
  entity_type: string | null;
  entity_id: string | null;
  is_read: boolean;
  created_at: string | null;
}

export interface NotificationList {
  items: NotificationItem[];
  unread_count: number;
}

export interface UploadResult {
  key: string;
  url: string;
}

// ---------- Phase 3: forms / swaps / approvals ----------

export type FormFieldType =
  | "text"
  | "number"
  | "select"
  | "photo"
  | "voice_note"
  | "datetime"
  | "toggle"
  | "gps_point";

export interface FormFieldDef {
  key: string;
  type: FormFieldType;
  label_en: string;
  label_hi: string;
  label_mr: string;
  required: boolean;
  options: string[] | null;
  ai_hook: string | null;
  validation: { min?: number; max?: number; regex?: string } | null;
}

export interface FormDefinitionItem {
  id: string;
  department_code: string;
  code: string;
  title_en: string;
  title_hi: string;
  title_mr: string;
  schema_json: { fields: FormFieldDef[] };
  version: number;
  is_active: boolean;
  requires_approval: boolean;
  approval_role_code: string | null;
}

export type SubmissionStatus = "submitted" | "approved" | "rejected" | "escalated";

export interface SubmissionItem {
  id: string;
  form_definition_id: string;
  form_code: string | null;
  form_version: number;
  submitted_by: string;
  department_code: string;
  data_json: Record<string, unknown>;
  photos: string[];
  gps_lat: number | null;
  gps_lng: number | null;
  status: SubmissionStatus;
  approver_id: string | null;
  approved_at: string | null;
  rejection_reason: string | null;
  escalated_to: string | null;
  escalated_at: string | null;
  created_at: string | null;
  form_title_en?: string;
  form_title_hi?: string;
  form_title_mr?: string;
  submitted_by_name?: string | null;
  submitted_by_emp_id?: string | null;
}

export interface SubmissionList {
  items: SubmissionItem[];
  total: number;
  page: number;
  page_size: number;
}

export type SwapStatus = "pending_target" | "pending_manager" | "approved" | "rejected" | "cancelled";

export interface SwapRequest {
  id: string;
  requester_id: string;
  target_id: string;
  swap_date: string;
  status: SwapStatus;
  target_responded_at: string | null;
  manager_id: string | null;
  manager_responded_at: string | null;
  reason: string | null;
  created_at: string | null;
  requester_name: string | null;
  requester_emp_id: string | null;
  target_name: string | null;
  target_emp_id: string | null;
  department_code: string | null;
  requester_shift_code: string | null;
  target_shift_code: string | null;
}

export interface SwapCandidate {
  employee_id: string;
  emp_id: string;
  full_name: string;
  shift_code: string;
}

export interface SwapCandidates {
  date: string;
  my_shift_code: string | null;
  candidates: SwapCandidate[];
}

export interface FlaggedAttendance extends AttendanceRecord {
  employee_name: string;
  emp_id: string;
  department_code: string;
  selfie_url: string | null;
  reference_selfie_url: string | null;
}

// ---------- Phase 4: AI services ----------

export interface AnprResult {
  plate: string | null;
  confidence: number;
  valid: boolean;
  source: string | null;
  model: string;
}

export interface GaugeResult {
  value: number | null;
  unit: string | null;
  confidence: number;
  in_range: boolean | null;
  model: string;
}

export interface VoiceFillResult {
  transcript: string;
  language: string;
  fields: Record<string, unknown>;
  model: string;
}

export interface ChatCitation {
  doc_title: string;
  page: number;
}

export interface ChatResult {
  conversation_id: string;
  answer: string;
  citations: ChatCitation[];
  model: string;
}
