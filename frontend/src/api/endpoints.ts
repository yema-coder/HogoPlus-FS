import { api } from "@/src/api/client";
import type {
  AnprResult,
  AttendanceRecord,
  ChatResult,
  DepartmentItem,
  EmployeeProfile,
  FlaggedAttendance,
  FormDefinitionItem,
  GaugeResult,
  OnboardingHistoryRow,
  PendingRegistration,
  Incident,
  IncidentDetail,
  NotificationList,
  NotificationItem,
  ShiftDay,
  SubmissionItem,
  SubmissionList,
  SwapCandidates,
  SwapRequest,
  TokenPair,
  VerifyOtpResponse,
  VoiceFillResult,
} from "@/src/api/types";

export const sendOtp = (phone: string) =>
  api<{ message: string; otp_mode: string; expires_in?: number; resend_after?: number }>(
    "/auth/send-otp",
    {
      method: "POST",
      body: { phone },
      auth: false,
    },
  );

export const verifyOtp = (phone: string, otp: string) =>
  api<VerifyOtpResponse>("/auth/verify-otp", { method: "POST", body: { phone, otp }, auth: false });

export const registerEmployee = (
  body: {
    phone: string;
    full_name: string;
    selfie_key: string;
    lat?: number;
    lng?: number;
    address?: string;
    device?: string;
    app_version?: string;
  },
  registrationToken: string,
) =>
  api<TokenPair & { employee: EmployeeProfile }>("/auth/register", {
    method: "POST",
    body,
    tokenOverride: registrationToken,
  });

export const getMe = () => api<EmployeeProfile>("/auth/me");

export const patchMe = (body: { language_pref?: string; expo_push_token?: string }) =>
  api<EmployeeProfile>("/employees/me", { method: "PATCH", body });

export const listDepartments = () => api<DepartmentItem[]>("/departments", { auth: false });

export const createIncident = (body: Record<string, unknown>) =>
  api<Incident>("/incidents", { method: "POST", body });

export const myIncidents = () => api<Incident[]>("/incidents/mine");

export const incidentDetail = (id: string) => api<IncidentDetail>(`/incidents/${id}`);

export const listIncidents = (params: { status?: string; department_code?: string } = {}) => {
  const q = new URLSearchParams();
  if (params.status) q.set("status", params.status);
  if (params.department_code) q.set("department_code", params.department_code);
  const qs = q.toString();
  return api<Incident[]>(`/incidents${qs ? `?${qs}` : ""}`);
};

export const changeIncidentStatus = (
  id: string,
  status: string,
  note?: string,
  resolutionPhotoKey?: string,
) =>
  api<Incident>(`/incidents/${id}/status`, {
    method: "POST",
    body: { status, note, resolution_photo_key: resolutionPhotoKey ?? null },
  });

export const confirmIncidentRouting = (
  id: string,
  body: { category?: string; department_code?: string; severity?: string } = {},
) => api<Incident>(`/incidents/${id}/confirm-routing`, { method: "POST", body });

export const punchIn = (body: Record<string, unknown>) =>
  api<AttendanceRecord>("/attendance/punch-in", { method: "POST", body });

export const beaconMacs = () => api<{ macs: string[] }>("/attendance/beacon-macs");

export interface RegistryZoneLabels {
  zone_en?: string;
  zone_hi?: string;
  zone_mr?: string;
}

export const beaconRegistry = () =>
  api<{
    macs: string[];
    ibeacons: ({ uuid: string; major: number; minor: number } & RegistryZoneLabels)[];
    macs_detail?: ({ mac: string } & RegistryZoneLabels)[];
  }>(
    "/attendance/beacon-registry",
  );

export const punchOut = () => api<AttendanceRecord>("/attendance/punch-out", { method: "POST" });

export const myAttendance = (month: string) =>
  api<AttendanceRecord[]>(`/attendance/mine?month=${month}`);

export const myShifts = () => api<ShiftDay[]>("/shifts/mine");

export const myNotifications = () => api<NotificationList>("/notifications/mine");

export const markNotificationRead = (id: string) =>
  api<NotificationItem>(`/notifications/${id}/read`, { method: "POST" });

// ---------- Phase 3: forms / swaps / approvals ----------

export const listForms = (departmentCode?: string) =>
  api<FormDefinitionItem[]>(
    `/forms${departmentCode ? `?department_code=${departmentCode}` : ""}`,
  );

export const submitForm = (
  definitionId: string,
  body: {
    data_json: Record<string, unknown>;
    photos: string[];
    gps_lat?: number | null;
    gps_lng?: number | null;
    address_text?: string | null;
  },
) => api<SubmissionItem>(`/forms/${definitionId}/submit`, { method: "POST", body });

export const listSubmissions = (
  params: { status?: string; department_code?: string; scope?: string; page_size?: number } = {},
) => {
  const q = new URLSearchParams();
  if (params.status) q.set("status", params.status);
  if (params.department_code) q.set("department_code", params.department_code);
  if (params.scope) q.set("scope", params.scope);
  q.set("page_size", String(params.page_size ?? 50));
  return api<SubmissionList>(`/submissions?${q.toString()}`);
};

export const submissionDetail = (id: string) => api<SubmissionItem>(`/submissions/${id}`);

export const approveSubmission = (id: string) =>
  api<SubmissionItem>(`/submissions/${id}/approve`, { method: "POST" });

export const rejectSubmission = (id: string, reason: string) =>
  api<SubmissionItem>(`/submissions/${id}/reject`, { method: "POST", body: { reason } });

export const pendingEmployees = () => api<PendingRegistration[]>("/admin/employees/pending");
export const employeeHistory = (id: string) =>
  api<OnboardingHistoryRow[]>(`/admin/employees/${id}/history`);

export const approveEmployee = (
  id: string,
  body: { department_code: string; role_code: string; emp_id: string },
) => api<EmployeeProfile>(`/admin/employees/${id}/approve`, { method: "POST", body });

export const rejectEmployee = (id: string, reason: string) =>
  api<EmployeeProfile>(`/admin/employees/${id}/reject`, { method: "POST", body: { reason } });

export const swapCandidates = (date: string) =>
  api<SwapCandidates>(`/shift-swaps/candidates?date=${date}`);

export const createSwap = (body: { target_employee_id: string; swap_date: string; reason?: string | null }) =>
  api<SwapRequest>("/shift-swaps", { method: "POST", body });

export const respondSwap = (id: string, accept: boolean) =>
  api<SwapRequest>(`/shift-swaps/${id}/respond`, { method: "POST", body: { accept } });

export const decideSwap = (id: string, approve: boolean, reason?: string) =>
  api<SwapRequest>(`/shift-swaps/${id}/decide`, { method: "POST", body: { approve, reason } });

export const cancelSwap = (id: string) =>
  api<SwapRequest>(`/shift-swaps/${id}/cancel`, { method: "POST" });

export const mySwaps = () => api<SwapRequest[]>("/shift-swaps/mine");

export const pendingSwaps = () => api<SwapRequest[]>("/shift-swaps/pending");

export const flaggedAttendance = (date?: string) =>
  api<FlaggedAttendance[]>(`/attendance/flagged${date ? `?date=${date}` : ""}`);

export const approveAttendance = (id: string) =>
  api<AttendanceRecord>(`/attendance/${id}/approve`, { method: "POST" });

export const rejectAttendance = (id: string) =>
  api<AttendanceRecord>(`/attendance/${id}/reject`, { method: "POST" });

/** v1.0.16 field instrumentation: ship a BLE diagnostic report to the server. */
export const sendBleDiag = (report: unknown) =>
  api<{ stored: boolean }>("/attendance/ble-diag", { method: "POST", body: { report } });

/** v1.0.17 speed pack: attach a late-arriving beacon match to a just-created punch. */
export const attachBeacon = (id: string, body: Record<string, unknown>) =>
  api<AttendanceRecord>(`/attendance/${id}/attach-beacon`, { method: "POST", body });

// ---------- Phase 4: AI services ----------

export const aiAnpr = (photoKey: string) =>
  api<AnprResult>("/ai/anpr", { method: "POST", body: { photo_key: photoKey } });

export const aiGaugeRead = (photoKey: string, expectedMin?: number, expectedMax?: number) =>
  api<GaugeResult>("/ai/gauge-read", {
    method: "POST",
    body: { photo_key: photoKey, expected_min: expectedMin ?? null, expected_max: expectedMax ?? null },
  });

export const aiVoiceFill = (audioKey: string, formDefinitionId: string) =>
  api<VoiceFillResult>("/ai/voice-fill", {
    method: "POST",
    body: { audio_key: audioKey, form_definition_id: formDefinitionId },
  });

export const aiVoiceDescribe = (audioKey: string) =>
  api<{ transcript: string; description: string; language: string }>("/ai/voice-describe", {
    method: "POST",
    body: { audio_key: audioKey },
  });

export const aiChat = (message: string, conversationId?: string | null) =>
  api<ChatResult>("/ai/chat", {
    method: "POST",
    body: { message, conversation_id: conversationId ?? null },
  });

export const getAppVersion = () =>
  api<{
    latest_version: string | null;
    apk_url: string | null;
    notes: string | null;
    force_update?: boolean;
  }>(
    "/app-version",
    { auth: false },
  );

// ---------------- Prompt 17 ----------------

export const faceEnroll = (selfieKey: string) =>
  api<EmployeeProfile>("/employees/me/face-enroll", {
    method: "POST",
    body: { selfie_key: selfieKey },
  });

export const escalationTargets = () =>
  api<import("./types").EscalationTarget[]>("/incidents/escalation-targets");

export const escalateIncident = (
  id: string,
  body: { mode: "department" | "employee"; department_code?: string; employee_id?: string; reason: string },
) => api<Incident>(`/incidents/${id}/escalate`, { method: "POST", body });

export const sendAnnouncement = (body: {
  title: string;
  message: string;
  audience: "all" | "department";
  department_code?: string;
}) => api<{ sent: boolean; recipients: number }>("/admin/announcements", { method: "POST", body });

export const searchEmployees = (search: string) =>
  api<EmployeeProfile[]>(`/admin/employees?search=${encodeURIComponent(search)}`);

export const empIdSuggest = () => api<{ suggested_emp_id: string }>("/admin/emp-id-suggest");

export const directAddEmployee = (body: {
  full_name: string;
  phone: string;
  department_code: string;
  role_code: string;
  shift_code?: string;
  emp_id: string;
}) => api<EmployeeProfile>("/admin/employees", { method: "POST", body });

export const patchEmployee = (
  id: string,
  body: Partial<{
    phone: string;
    full_name: string;
    role_code: string;
    department_code: string;
    shift_code: string;
    is_active: boolean;
  }>,
) => api<EmployeeProfile>(`/admin/employees/${id}`, { method: "PATCH", body });

/** Prompt 21: install an employee as a department's HOD (Time Office / CGM / MD). */
export const assignDeptManager = (code: string, employeeId: string) =>
  api<{ department_code: string; manager_employee_id: string; manager_name: string }>(
    `/admin/departments/${code}/assign-manager`,
    { method: "POST", body: { employee_id: employeeId } },
  );

// ---- Wave 1: config-driven home + Security vehicle log ----

export interface HomeWidgetItem {
  key?: string;
  icon?: string;
  emoji?: string;
  label?: Record<string, string>;
  route?: string;
  color?: string;
  testID?: string;
}
export interface HomeWidget {
  type: string;
  items?: HomeWidgetItem[];
}
export interface HomeConfigResult {
  config: { widgets: HomeWidget[] } | null;
}

export const getHomeConfig = () => api<HomeConfigResult>("/home/config");
export const getHomeCounts = () => api<Record<string, number>>("/home/counts");

export interface VehicleLogItem {
  id: string;
  plate: string;
  vehicle_type: string;
  direction: "in" | "out";
  driver_name: string | null;
  purpose: string | null;
  photo_key: string | null;
  voice_note_key: string | null;
  gate_zone: string | null;
  anpr_used: boolean;
  paired_log_id: string | null;
  logged_at: string;
  hours_inside?: number;
}

export const createVehicleLog = (body: Record<string, unknown>) =>
  api<{ log: VehicleLogItem; duplicate: boolean }>("/vehicles/log", { method: "POST", body });

export const listVehicleLogs = (params: { day?: string; plate?: string; direction?: string } = {}) => {
  const qs = Object.entries(params)
    .filter(([, v]) => v)
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`)
    .join("&");
  return api<VehicleLogItem[]>(`/vehicles/logs${qs ? `?${qs}` : ""}`);
};

export const vehiclesInside = () => api<VehicleLogItem[]>("/vehicles/inside");

export const vehiclesSummary = () =>
  api<{ today_in: number; today_out: number; currently_inside: number }>("/vehicles/summary");
