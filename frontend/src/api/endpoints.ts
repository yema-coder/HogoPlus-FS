import { api } from "@/src/api/client";
import type {
  AttendanceRecord,
  DepartmentItem,
  EmployeeProfile,
  Incident,
  IncidentDetail,
  NotificationList,
  NotificationItem,
  ShiftDay,
  TokenPair,
  VerifyOtpResponse,
} from "@/src/api/types";

export const sendOtp = (phone: string) =>
  api<{ message: string; otp_mode: string }>("/auth/send-otp", {
    method: "POST",
    body: { phone },
    auth: false,
  });

export const verifyOtp = (phone: string, otp: string) =>
  api<VerifyOtpResponse>("/auth/verify-otp", { method: "POST", body: { phone, otp }, auth: false });

export const registerEmployee = (
  body: { phone: string; full_name: string; department_code: string; selfie_key: string },
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

export const changeIncidentStatus = (id: string, status: string, note?: string) =>
  api<Incident>(`/incidents/${id}/status`, { method: "POST", body: { status, note } });

export const punchIn = (body: Record<string, unknown>) =>
  api<AttendanceRecord>("/attendance/punch-in", { method: "POST", body });

export const punchOut = () => api<AttendanceRecord>("/attendance/punch-out", { method: "POST" });

export const myAttendance = (month: string) =>
  api<AttendanceRecord[]>(`/attendance/mine?month=${month}`);

export const myShifts = () => api<ShiftDay[]>("/shifts/mine");

export const myNotifications = () => api<NotificationList>("/notifications/mine");

export const markNotificationRead = (id: string) =>
  api<NotificationItem>(`/notifications/${id}/read`, { method: "POST" });
