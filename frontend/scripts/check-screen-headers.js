#!/usr/bin/env node
/* eslint-disable */
/**
 * REGRESSION GUARD — shared back-button header (v1.0.25).
 *
 * Every navigable screen in app/ MUST render <ScreenHeader …> (the single
 * shared header with the back button) unless it is explicitly exempted below.
 * Fails the build (exit 1) when a non-root route lacks the header, so a screen
 * can never ship without a back button again.
 *
 * Run: node scripts/check-screen-headers.js   (or: yarn check:headers)
 */
const fs = require("fs");
const path = require("path");

const APP_DIR = path.join(__dirname, "..", "app");

/** Routes allowed WITHOUT the shared header — each with a written reason. */
const EXEMPT = {
  "index.tsx": "root redirect — renders splash only, immediately redirects",
  "+html.tsx": "web-only HTML shell, not a screen",
  "permissions.tsx": "one-time onboarding gate (forward-only by design, like auth)",
  "(auth)/language.tsx": "first screen of the app — nothing to go back to",
  "(auth)/phone.tsx": "auth root — back would leave the auth flow",
  "(auth)/otp.tsx": "has its own explicit 'Change number' back affordance",
  "(auth)/pending.tsx": "approval waiting room — logout is the only exit",
  "(tabs)/home.tsx": "root tab — hardware back = double-press-to-exit",
};

function walk(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) return walk(p);
    return e.name.endsWith(".tsx") ? [p] : [];
  });
}

const failures = [];
const passed = [];
const exempted = [];

for (const file of walk(APP_DIR).sort()) {
  const rel = path.relative(APP_DIR, file);
  if (path.basename(rel) === "_layout.tsx") continue; // navigators, not screens
  if (EXEMPT[rel]) {
    exempted.push(`${rel}  (${EXEMPT[rel]})`);
    continue;
  }
  const src = fs.readFileSync(file, "utf8");
  if (src.includes("<ScreenHeader")) passed.push(rel);
  else failures.push(rel);
}

console.log("Shared back-button header guard");
console.log("================================");
console.log(`✓ ${passed.length} screens render <ScreenHeader>`);
for (const p of passed) console.log(`  ✓ ${p}`);
console.log(`− ${exempted.length} exempt (documented):`);
for (const e of exempted) console.log(`  − ${e}`);

if (failures.length) {
  console.error(`\n✗ FAIL — ${failures.length} screen(s) missing the shared header:`);
  for (const f of failures) console.error(`  ✗ ${f}`);
  console.error("\nAdd <ScreenHeader title={…} /> from '@/src/components/ScreenHeader',");
  console.error("or add an exemption WITH A REASON in scripts/check-screen-headers.js.");
  process.exit(1);
}
console.log("\nPASS — every non-root route has the shared back-button header.");
