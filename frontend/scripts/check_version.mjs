#!/usr/bin/env node
/**
 * Pre-publish version guard.
 *
 * Guarantees the Android `versionCode` strictly increases on every build so Google Play
 * (and the in-app update gate) always offer the update instead of silently doing nothing.
 *
 * Scheme (deterministic, monotonic):
 *   version "A.B.C"  ->  versionCode = A*10000 + B*100 + C
 *   e.g. 1.0.27 -> 10027,  1.1.0 -> 10100,  2.0.0 -> 20000
 *
 * It (1) checks app.json's versionCode matches the scheme, and (2) checks it is strictly
 * greater than the last shipped floor recorded in scripts/.version_floor. Run before every
 * Publish:  `node scripts/check_version.mjs`  (add `--commit` to advance the floor after a
 * successful build).
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const dir = path.dirname(fileURLToPath(import.meta.url));
const appJsonPath = path.join(dir, "..", "app.json");
const floorPath = path.join(dir, ".version_floor");

const expo = JSON.parse(fs.readFileSync(appJsonPath, "utf8")).expo;
const version = expo.version;
const code = expo.android?.versionCode;

const m = /^(\d+)\.(\d+)\.(\d+)$/.exec(version);
if (!m) {
  console.error(`❌ version "${version}" must be A.B.C (three integers).`);
  process.exit(1);
}
const expected = Number(m[1]) * 10000 + Number(m[2]) * 100 + Number(m[3]);
if (code !== expected) {
  console.error(
    `❌ android.versionCode is ${code} but version ${version} requires ${expected}. ` +
      `Fix app.json so they match the scheme.`,
  );
  process.exit(1);
}

const floor = fs.existsSync(floorPath) ? Number(fs.readFileSync(floorPath, "utf8").trim()) : 0;
if (code <= floor) {
  console.error(
    `❌ versionCode ${code} is NOT greater than the last shipped build (${floor}). ` +
      `Bump the version in app.json before publishing.`,
  );
  process.exit(1);
}

if (process.argv.includes("--commit")) {
  fs.writeFileSync(floorPath, String(code));
  console.log(`✅ ${version} (${code}) OK — floor advanced to ${code}.`);
} else {
  console.log(`✅ ${version} (${code}) OK — greater than last shipped ${floor}.`);
  console.log("   After a successful Publish, run: node scripts/check_version.mjs --commit");
}
