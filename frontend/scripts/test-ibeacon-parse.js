#!/usr/bin/env node
/**
 * v1.0.16 unit test for the SHIPPED iBeacon parse/match path (src/ble/ibeaconParse.ts),
 * run against real ble-plx-shaped payloads. Compiles the TS module with tsc, then:
 *  - eliminates hypotheses (a) case sensitivity, (b) type mismatch, (c) uuid format
 *  - reproduces the ACTUAL v1.0.13–15 failure mode: ble-plx's single manufacturerData
 *    field clobbered by the vendor's scan-response frame → old parser returns null,
 *    new extractIBeacons() recovers the iBeacon from rawScanRecord.
 * Usage: node scripts/test-ibeacon-parse.js   (exit 0 = all pass)
 */
const { execSync } = require("child_process");
const path = require("path");

const root = path.join(__dirname, "..");
execSync(
  "npx tsc src/ble/ibeaconParse.ts --outDir /tmp/bletest --module commonjs --target es2020 --esModuleInterop --skipLibCheck --types node",
  { cwd: root, stdio: "inherit" },
);
const { extractIBeacons, ibKey, classifyCandidate } = require("/tmp/bletest/ibeaconParse.js");

const UUID_BYTES = [0x01, 0x12, 0x23, 0x34, 0x45, 0x56, 0x67, 0x78, 0x89, 0x9a, 0xab, 0xbc, 0xcd, 0xde, 0xef, 0xf0];
const b64 = (bytes) => Buffer.from(bytes).toString("base64");
// exact ble-plx manufacturerData shape: company id LE + 0x02 0x15 + uuid + major BE + minor BE + tx
const appleMfg = (major, minor) => [0x4c, 0x00, 0x02, 0x15, ...UUID_BYTES, major >> 8, major & 0xff, minor >> 8, minor & 0xff, 0xc5];
// a vendor (e.g. 0x0059 Nordic-style) config frame like the SmartConfig app uses
const vendorMfg = [0x59, 0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08];
// full merged Android scan record: flags AD + Apple iBeacon AD + vendor AD (scan response, LAST)
const rawScanRecord = (major, minor) => [
  0x02, 0x01, 0x06,                       // flags
  0x1a, 0xff, ...appleMfg(major, minor),  // len 26, type 0xFF, apple iBeacon
  0x0b, 0xff, ...vendorMfg,               // len 11, type 0xFF, vendor frame (clobbers ble-plx manufacturerData)
];

// the EXACT parser that shipped in v1.0.13–v1.0.15 (header-anchored, single frame)
function oldParseIBeacon(b64s) {
  const b = Buffer.from(b64s, "base64");
  if (b.length < 25) return null;
  if (b[0] !== 0x4c || b[1] !== 0x00 || b[2] !== 0x02 || b[3] !== 0x15) return null;
  const hex = [...b.slice(4, 20)].map((x) => x.toString(16).padStart(2, "0")).join("");
  const uuid = `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  return { uuid, major: (b[20] << 8) | b[21], minor: (b[22] << 8) | b[23] };
}

const REG_LOWER = [{ uuid: "01122334-4556-6778-899a-abbccddeeff0", major: 1, minor: 22 }];
let failures = 0;
const check = (name, cond, detail = "") => {
  console.log(`${cond ? "PASS" : "FAIL"}  ${name}${detail ? "  → " + detail : ""}`);
  if (!cond) failures++;
};

// ── Hypothesis (a) CASE SENSITIVITY — eliminated ─────────────────────────────
const cands1 = extractIBeacons(b64(appleMfg(1, 22)));
check("(a1) parse emits lowercase hyphenated uuid", cands1.length === 1 && cands1[0].uuid === "01122334-4556-6778-899a-abbccddeeff0", JSON.stringify(cands1[0]));
check("(a2) match vs LOWERCASE registry", classifyCandidate(cands1[0], REG_LOWER) === "matched");
check("(a3) match vs UPPERCASE registry row", classifyCandidate(cands1[0], [{ uuid: "01122334-4556-6778-899A-ABBCCDDEEFF0", major: 1, minor: 22 }]) === "matched");
check("(a4) ibKey is case-insensitive", ibKey({ uuid: "ABCD-EF", major: 1, minor: 2 }) === ibKey({ uuid: "abcd-ef", major: 1, minor: 2 }));

// ── Hypothesis (b) TYPE MISMATCH — eliminated ────────────────────────────────
check("(b1) string-typed registry major/minor still match", classifyCandidate(cands1[0], [{ uuid: "01122334-4556-6778-899a-abbccddeeff0", major: "1", minor: "22" }]) === "matched");
check("(b2) parse offsets: major=1 minor=22 from BE bytes", cands1[0].major === 1 && cands1[0].minor === 22);
const m0 = extractIBeacons(b64(appleMfg(1, 0)))[0];
check("(b3) minor 0 parses and matches (Civil)", m0.minor === 0 && classifyCandidate(m0, [{ uuid: "01122334-4556-6778-899a-abbccddeeff0", major: 1, minor: 0 }]) === "matched");

// ── Hypothesis (c) UUID FORMAT — eliminated ──────────────────────────────────
check("(c1) emitted uuid is hyphenated 8-4-4-4-12", /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(cands1[0].uuid));

// ── THE REAL v1.0.13–15 FAILURE MODE (ble-plx manufacturerData clobbering) ───
check("(d1) OLD parser on clean Apple mfg payload works", JSON.stringify(oldParseIBeacon(b64(appleMfg(1, 22)))) === JSON.stringify(cands1[0]), "old code was correct for the frame it was given");
check("(d2) OLD parser on vendor-clobbered manufacturerData returns null", oldParseIBeacon(b64([...vendorMfg, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])) === null, "ble-plx hands the app the LAST 0xFF frame — the vendor's");
const candsRaw = extractIBeacons(b64(rawScanRecord(1, 22)));
check("(d3) NEW extractor recovers iBeacon from rawScanRecord with vendor frame present", candsRaw.length === 1 && classifyCandidate(candsRaw[0], REG_LOWER) === "matched", JSON.stringify(candsRaw));
check("(d4) NEW extractor on vendor-only payload finds nothing (no false positives)", extractIBeacons(b64(vendorMfg)).length === 0);
check("(d5) NEW extractor still handles bare ble-plx manufacturerData", extractIBeacons(b64(appleMfg(1, 22))).length === 1);

// ── Rejection classification (diagnostics) ───────────────────────────────────
check("(e1) wrong uuid → uuid_mismatch", classifyCandidate({ uuid: "ffffffff-0000-0000-0000-000000000000", major: 1, minor: 22 }, REG_LOWER) === "uuid_mismatch");
check("(e2) wrong major → major_mismatch", classifyCandidate({ uuid: REG_LOWER[0].uuid, major: 9, minor: 22 }, REG_LOWER) === "major_mismatch");
check("(e3) unregistered minor → minor_not_registered", classifyCandidate({ uuid: REG_LOWER[0].uuid, major: 1, minor: 99 }, REG_LOWER) === "minor_not_registered");

console.log(failures === 0 ? "\nALL TESTS PASSED" : `\n${failures} FAILURES`);
process.exit(failures === 0 ? 0 : 1);
