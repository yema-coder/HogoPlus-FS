#!/usr/bin/env node
/**
 * i18n key-parity check — fails (exit 1) if any key is missing in any language.
 * Run: node scripts/i18n-parity.js
 */
const fs = require("fs");
const path = require("path");

const dir = path.join(__dirname, "..", "src", "i18n", "locales");
const langs = ["en", "hi", "mr"];

function flatten(obj, prefix = "") {
  const keys = [];
  for (const [k, v] of Object.entries(obj)) {
    const full = prefix ? `${prefix}.${k}` : k;
    if (v && typeof v === "object") keys.push(...flatten(v, full));
    else keys.push(full);
  }
  return keys;
}

const keySets = {};
for (const lang of langs) {
  const data = JSON.parse(fs.readFileSync(path.join(dir, `${lang}.json`), "utf8"));
  keySets[lang] = new Set(flatten(data));
}

const union = new Set();
for (const lang of langs) for (const k of keySets[lang]) union.add(k);

let failed = false;
for (const lang of langs) {
  const missing = [...union].filter((k) => !keySets[lang].has(k));
  if (missing.length) {
    failed = true;
    console.error(`✗ ${lang}.json missing ${missing.length} key(s):`);
    for (const k of missing) console.error(`   - ${k}`);
  } else {
    console.log(`✓ ${lang}.json — ${keySets[lang].size} keys, complete`);
  }
}

// also check for empty values
for (const lang of langs) {
  const data = JSON.parse(fs.readFileSync(path.join(dir, `${lang}.json`), "utf8"));
  const empty = flatten(data).filter((k) => {
    const val = k.split(".").reduce((o, part) => (o ? o[part] : undefined), data);
    return typeof val !== "string" || val.trim() === "";
  });
  if (empty.length) {
    failed = true;
    console.error(`✗ ${lang}.json has empty values: ${empty.join(", ")}`);
  }
}

if (failed) {
  console.error("i18n parity check FAILED");
  process.exit(1);
}
console.log(`i18n parity check PASSED — ${union.size} keys × ${langs.length} languages`);
