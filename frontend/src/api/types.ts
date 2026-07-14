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
  photo_key: string;
  gps_lat: number | null;
  gps_lng: number | null;
  description: string | null;
  voice_note_key: string | null;
  status: IncidentStatus;
  severity: string;
  assigned_manager_id: string | null;
  resolved_at: string | null;
  resolution_note: string | null;
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
