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
  nav_vehicles: ["Vehicles", "वाहन", "वाहने"],
  // Password login (Prompt 7)
  otpLoginTab: ["OTP login", "OTP लॉगिन", "OTP लॉगिन"],
  passwordLoginTab: ["Password login", "पासवर्ड लॉगिन", "पासवर्ड लॉगिन"],
  password: ["Password", "पासवर्ड", "पासवर्ड"],
  loginBtn: ["Sign in", "साइन इन करें", "साइन इन करा"],
  pwdLoginHint: [
    "Password login is for MD / CGM only.",
    "पासवर्ड लॉगिन केवल MD / CGM के लिए है।",
    "पासवर्ड लॉगिन फक्त MD / CGM साठी आहे.",
  ],
  mustChangePwd: ["Set a new password", "नया पासवर्ड सेट करें", "नवीन पासवर्ड सेट करा"],
  mustChangePwdMsg: [
    "You are using a temporary password. Choose a new one (min 8 characters).",
    "आप अस्थायी पासवर्ड उपयोग कर रहे हैं। नया पासवर्ड चुनें (कम से कम 8 अक्षर)।",
    "तुम्ही तात्पुरता पासवर्ड वापरत आहात. नवीन पासवर्ड निवडा (किमान 8 अक्षरे).",
  ],
  newPassword: ["New password", "नया पासवर्ड", "नवीन पासवर्ड"],
  currentPassword: ["Current password", "वर्तमान पासवर्ड", "सध्याचा पासवर्ड"],
  confirmPassword: ["Confirm new password", "नया पासवर्ड दोबारा", "नवीन पासवर्ड पुन्हा"],
  changePassword: ["Change password", "पासवर्ड बदलें", "पासवर्ड बदला"],
  pwdChanged: ["Password changed", "पासवर्ड बदल गया", "पासवर्ड बदलला"],
  pwdTooShort: ["Minimum 8 characters", "कम से कम 8 अक्षर", "किमान 8 अक्षरे"],
  pwdMismatch: ["Passwords do not match", "पासवर्ड मेल नहीं खाते", "पासवर्ड जुळत नाहीत"],
  // Vehicles / plate search (Prompt 7)
  plateSearchHint: ["Enter plate e.g. MH12AB1234 (partial ok)", "प्लेट दर्ज करें जैसे MH12AB1234", "प्लेट टाका उदा. MH12AB1234"],
  results: ["Results", "परिणाम", "निकाल"],
  searchBtn: ["Search", "खोजें", "शोधा"],
  noPlateResults: ["No vehicles found for this plate", "इस प्लेट के लिए कुछ नहीं मिला", "या प्लेटसाठी काही सापडले नाही"],
  t_submission: ["Form", "फ़ॉर्म", "फॉर्म"],
  searchIncidents: ["Filter: plate / category / name / address", "फ़िल्टर: प्लेट / श्रेणी / नाम / पता", "फिल्टर: प्लेट / श्रेणी / नाव / पत्ता"],
  location: ["Location", "स्थान", "ठिकाण"],
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
  openIncidents: ["Open complaints", "खुली शिकायतें", "खुल्या तक्रारी"],
  critical: ["Critical", "गंभीर", "गंभीर"],
  pendingApprovals: ["Pending approvals", "लंबित अनुमोदन", "प्रलंबित मंजुरी"],
  submissionsToday: ["Submissions today", "आज के फ़ॉर्म", "आजचे फॉर्म"],
  // Overview
  deptHealth: ["Department health", "विभाग स्थिति", "विभागांची स्थिती"],
  liveIncidents: ["Live complaint feed", "लाइव शिकायतें", "थेट तक्रारी"],
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
  t_incident: ["Complaint", "शिकायत", "तक्रार"],
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
  // BLE beacons (MAC-based vendor beacons)
  beacons: ["BLE beacons", "BLE बीकन", "BLE बीकन"],
  macAddress: ["MAC address", "MAC पता", "MAC पत्ता"],
  zoneEn: ["Zone (English)", "क्षेत्र (अंग्रेज़ी)", "झोन (इंग्रजी)"],
  zoneHi: ["Zone (Hindi)", "क्षेत्र (हिंदी)", "झोन (हिंदी)"],
  zoneMr: ["Zone (Marathi)", "क्षेत्र (मराठी)", "झोन (मराठी)"],
  addBeacon: ["Add beacon", "बीकन जोड़ें", "बीकन जोडा"],
  invalidMac: ["MAC must be AA:BB:CC:DD:EE:FF", "MAC प्रारूप AA:BB:CC:DD:EE:FF होना चाहिए", "MAC स्वरूप AA:BB:CC:DD:EE:FF असावे"],
  active: ["Active", "सक्रिय", "सक्रिय"],
  inactive: ["Inactive", "निष्क्रिय", "निष्क्रिय"],
  // ANPR result card (Prompt 9)
  detectedPlate: ["Detected Number Plate", "पहचानी गई नंबर प्लेट", "ओळखलेली नंबर प्लेट"],
  plateNotDetected: ["Number Plate Not Detected", "नंबर प्लेट नहीं मिली", "नंबर प्लेट आढळली नाही"],
  plateChecking: ["Checking for number plate…", "नंबर प्लेट जाँची जा रही है…", "नंबर प्लेट तपासली जात आहे…"],
  confidence: ["Confidence", "विश्वसनीयता", "विश्वासार्हता"],
  copy: ["Copy", "कॉपी", "कॉपी"],
  copied: ["Copied", "कॉपी हो गया", "कॉपी झाले"],
  objectLocation: ["Object Location", "वस्तु का स्थान", "वस्तूचे स्थान"],
  voiceNote: ["Voice note", "आवाज़ नोट", "आवाज नोट"],
  deviceLocation: ["Device Location", "डिवाइस का स्थान", "डिव्हाइसचे स्थान"],
  capturedAt: ["Captured at", "कैप्चर समय", "कॅप्चर वेळ"],
  rNoText: ["No text found in the photo", "फोटो में कोई टेक्स्ट नहीं मिला", "फोटोमध्ये मजकूर आढळला नाही"],
  rNoValidPlate: ["Text found but not a valid plate", "टेक्स्ट मिला पर मान्य नंबर प्लेट नहीं", "मजकूर आढळला पण वैध नंबर प्लेट नाही"],
  rDetectionFailed: ["Plate check failed", "प्लेट जाँच विफल", "प्लेट तपासणी अयशस्वी"],
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
