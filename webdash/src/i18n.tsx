import React, { createContext, useContext, useState } from "react";

export type Lang = "en" | "hi" | "mr";

const D: Record<string, [string, string, string]> = {
  // [en, hi, mr]
  brand: ["Hogo Plus", "होगो प्लस", "होगो प्लस"],
  commandCenter: ["Command Center", "कमांड सेंटर", "कमांड सेंटर"],
  nav_overview: ["Overview", "अवलोकन", "आढावा"],
  nav_approvals: ["Approvals", "अनुमोदन", "मंजुरी"],
  nav_attendance: ["Attendance", "उपस्थिति", "हजेरी"],
  nav_reports: ["Reports & AI", "रिपोर्ट और AI", "अहवाल आणि AI"],
  nav_admin: ["Admin", "एडमिन", "प्रशासन"],
  logout: ["Logout", "लॉग आउट", "बाहेर पडा"],
  signIn: ["Sign in", "साइन इन करें", "साइन इन करा"],
  phone: ["Phone number", "फ़ोन नंबर", "फोन नंबर"],
  sendOtp: ["Send OTP", "OTP भेजें", "OTP पाठवा"],
  otp: ["Enter OTP", "OTP दर्ज करें", "OTP टाका"],
  verify: ["Verify & sign in", "सत्यापित करें", "पडताळा आणि साइन इन"],
  otpSent: ["OTP sent", "OTP भेजा गया", "OTP पाठवला"],
  changePhone: ["Change number", "नंबर बदलें", "नंबर बदला"],
  accessDenied: ["Access restricted", "पहुँच प्रतिबंधित", "प्रवेश मर्यादित"],
  accessDeniedMsg: [
    "The Command Center is for Managers, CGM and MD only.",
    "कमांड सेंटर केवल प्रबंधक, CGM और MD के लिए है।",
    "कमांड सेंटर फक्त व्यवस्थापक, CGM आणि MD साठी आहे.",
  ],
  loading: ["Loading…", "लोड हो रहा है…", "लोड होत आहे…"],
  noData: ["Nothing here yet", "अभी कुछ नहीं", "अजून काही नाही"],
  refresh: ["Refresh", "रीफ्रेश", "रीफ्रेश"],
  save: ["Save", "सहेजें", "जतन करा"],
  saved: ["Saved", "सहेजा गया", "जतन केले"],
  search: ["Search name / emp id / phone", "नाम / आईडी / फ़ोन खोजें", "नाव / आयडी / फोन शोधा"],
  date: ["Date", "तारीख", "तारीख"],
  department: ["Department", "विभाग", "विभाग"],
  back: ["Back", "वापस", "मागे"],
  actions: ["Actions", "कार्रवाई", "कृती"],
  download: ["Download", "डाउनलोड", "डाउनलोड"],
  del: ["Delete", "हटाएँ", "हटवा"],
  upload: ["Upload PDF", "PDF अपलोड करें", "PDF अपलोड करा"],
  status: ["Status", "स्थिति", "स्थिती"],
  name: ["Name", "नाम", "नाव"],
  role: ["Role", "भूमिका", "भूमिका"],
  manager: ["Manager", "प्रबंधक", "व्यवस्थापक"],
  total: ["Total", "कुल", "एकूण"],
  // KPIs
  present: ["Present", "उपस्थित", "उपस्थित"],
  attendancePct: ["Attendance", "उपस्थिति", "हजेरी"],
  late: ["Late", "देरी से", "उशिरा"],
  flagged: ["Flagged", "फ़्लैग किए", "फ्लॅग केलेले"],
  openIncidents: ["Open incidents", "खुली घटनाएँ", "खुल्या घटना"],
  critical: ["Critical", "गंभीर", "गंभीर"],
  pendingApprovals: ["Pending approvals", "लंबित अनुमोदन", "प्रलंबित मंजुरी"],
  submissionsToday: ["Submissions today", "आज के फ़ॉर्म", "आजचे फॉर्म"],
  // Overview
  deptHealth: ["Department health", "विभाग स्थिति", "विभागांची स्थिती"],
  liveIncidents: ["Live incident feed", "लाइव घटनाएँ", "थेट घटना"],
  attendanceByDept: ["Attendance % by department", "विभागवार उपस्थिति %", "विभागनिहाय हजेरी %"],
  employees: ["employees", "कर्मचारी", "कर्मचारी"],
  // Department
  trends14: ["14-day trends", "14-दिन का रुझान", "14 दिवसांचा कल"],
  attendanceRegister: ["Attendance register", "उपस्थिति रजिस्टर", "हजेरी रजिस्टर"],
  submissions: ["Form submissions", "फ़ॉर्म सबमिशन", "फॉर्म सबमिशन"],
  punchIn: ["Punch in", "पंच इन", "पंच इन"],
  punchOut: ["Punch out", "पंच आउट", "पंच आउट"],
  verification: ["Verification", "सत्यापन", "पडताळणी"],
  reason: ["Reason", "कारण", "कारण"],
  empId: ["Emp ID", "कर्मचारी ID", "कर्मचारी ID"],
  noManager: ["No manager assigned", "कोई प्रबंधक नहीं", "व्यवस्थापक नाही"],
  // Approvals
  byManager: ["Pending by manager", "प्रबंधक अनुसार लंबित", "व्यवस्थापकानुसार प्रलंबित"],
  oldest: ["Oldest (hrs)", "सबसे पुराना (घंटे)", "सर्वात जुने (तास)"],
  pending: ["Pending", "लंबित", "प्रलंबित"],
  type: ["Type", "प्रकार", "प्रकार"],
  age: ["Age", "आयु", "वय"],
  escalated: ["Escalated", "एस्कलेटेड", "एस्कलेटेड"],
  t_form_submission: ["Form", "फ़ॉर्म", "फॉर्म"],
  t_registration: ["Registration", "पंजीकरण", "नोंदणी"],
  t_shift_swap: ["Shift swap", "शिफ्ट बदली", "शिफ्ट बदली"],
  t_incident: ["Incident", "घटना", "घटना"],
  // Attendance
  approve: ["Approve", "स्वीकृत करें", "मंजूर करा"],
  reject: ["Reject", "अस्वीकार करें", "नाकारा"],
  verified: ["Verified", "सत्यापित", "पडताळलेले"],
  pendingReview: ["Pending review", "समीक्षा लंबित", "पुनरावलोकन प्रलंबित"],
  faceScore: ["Face score", "फेस स्कोर", "फेस स्कोर"],
  rejected: ["Rejected", "अस्वीकृत", "नाकारले"],
  // Reports & AI
  dailyReports: ["Daily factory reports", "दैनिक फैक्ट्री रिपोर्ट", "दैनंदिन कारखाना अहवाल"],
  generate: ["Generate yesterday's report", "कल की रिपोर्ट बनाएँ", "कालचा अहवाल तयार करा"],
  generated: ["Report generated", "रिपोर्ट बनी", "अहवाल तयार झाला"],
  aiUsage: ["AI usage (7 days)", "AI उपयोग (7 दिन)", "AI वापर (7 दिवस)"],
  chatTitle: ["Ask Sahayak (SOP assistant)", "सहायक से पूछें (SOP)", "सहाय्यकाला विचारा (SOP)"],
  chatPh: ["Ask about factory SOPs…", "फैक्ट्री SOP के बारे में पूछें…", "कारखाना SOP बद्दल विचारा…"],
  send: ["Send", "भेजें", "पाठवा"],
  sources: ["Sources", "स्रोत", "स्रोत"],
  noReports: ["No reports yet", "अभी कोई रिपोर्ट नहीं", "अजून अहवाल नाहीत"],
  page: ["page", "पृष्ठ", "पान"],
  // Admin
  geofence: ["Factory geofence", "फैक्ट्री जियोफेंस", "कारखाना जिओफेन्स"],
  lat: ["Latitude", "अक्षांश", "अक्षांश"],
  lng: ["Longitude", "देशांतर", "रेखांश"],
  radius: ["Radius (meters)", "त्रिज्या (मीटर)", "त्रिज्या (मीटर)"],
  assignManager: ["Assign department manager", "विभाग प्रबंधक नियुक्त करें", "विभाग व्यवस्थापक नेमा"],
  assign: ["Assign", "नियुक्त करें", "नेमा"],
  assigned: ["Manager assigned", "प्रबंधक नियुक्त", "व्यवस्थापक नेमला"],
  missingPhones: ["Employees without phone", "बिना फ़ोन के कर्मचारी", "फोन नसलेले कर्मचारी"],
  changeRole: ["Change employee role", "कर्मचारी भूमिका बदलें", "कर्मचारी भूमिका बदला"],
  apply: ["Apply", "लागू करें", "लागू करा"],
  sopDocs: ["SOP documents", "SOP दस्तावेज़", "SOP दस्तऐवज"],
  backupNow: ["Backup now", "अभी बैकअप लें", "आता बॅकअप घ्या"],
  backupStarted: ["Backup started", "बैकअप शुरू", "बॅकअप सुरू"],
  audit: ["Audit trail", "ऑडिट ट्रेल", "ऑडिट ट्रेल"],
  hasManager: ["Has manager", "प्रबंधक है", "व्यवस्थापक आहे"],
  pages: ["pages", "पृष्ठ", "पाने"],
  chunks: ["chunks", "खंड", "खंड"],
};

const LangCtx = createContext<{ lang: Lang; setLang: (l: Lang) => void; t: (k: string) => string }>({
  lang: "en",
  setLang: () => {},
  t: (k) => k,
});

const IDX: Record<Lang, number> = { en: 0, hi: 1, mr: 2 };

export function LangProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLangState] = useState<Lang>(() => (localStorage.getItem("hogo_lang") as Lang) || "en");
  const setLang = (l: Lang) => {
    localStorage.setItem("hogo_lang", l);
    setLangState(l);
  };
  const t = (k: string) => (D[k] ? D[k][IDX[lang]] : k);
  return <LangCtx.Provider value={{ lang, setLang, t }}>{children}</LangCtx.Provider>;
}

export const useI18n = () => useContext(LangCtx);

/** pick name_en / name_hi / name_mr off an API object */
export function localName(obj: any, lang: Lang): string {
  return obj?.[`name_${lang}`] || obj?.name_en || "";
}
