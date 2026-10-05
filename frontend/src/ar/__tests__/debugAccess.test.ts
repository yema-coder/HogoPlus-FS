import { test } from "node:test";
import assert from "node:assert/strict";

import {
  AR_DEBUG_FOR_EVERYONE,
  AR_DEBUG_MIN_RANK,
  evaluateArDebug,
  isArDebugEnabled,
} from "../debugAccess.ts";

test("this build shows the AR debug dot + HUD to everyone", () => {
  assert.equal(AR_DEBUG_FOR_EVERYONE, true);
  // owner's own account: Manager, rank 3 — locked out by the old rank<=2 gate
  assert.equal(isArDebugEnabled({ rank: 3, empId: "0001" }), true);
  assert.equal(isArDebugEnabled({ rank: 6, empId: "D001" }), true);
  assert.equal(isArDebugEnabled(), true);
});

test("the real gate still works when AR_DEBUG_FOR_EVERYONE is turned off", () => {
  const gate = (ctx: Parameters<typeof evaluateArDebug>[0]) => evaluateArDebug(ctx, false, false);
  assert.equal(gate({ rank: 1 }), true); // MD
  assert.equal(gate({ rank: AR_DEBUG_MIN_RANK }), true); // CGM
  assert.equal(gate({ rank: 3 }), false); // Manager
  assert.equal(gate({ rank: 6 }), false); // Worker
  assert.equal(gate({}), false); // unknown rank
});

test("the server allowlist lets a specific emp_id in regardless of rank", () => {
  const gate = (ctx: Parameters<typeof evaluateArDebug>[0]) => evaluateArDebug(ctx, false, false);
  assert.equal(gate({ rank: 3, empId: "0001", allowlist: ["0001"] }), true);
  assert.equal(gate({ rank: 6, empId: "d500", allowlist: [" D500 "] }), true); // trim + case
  assert.equal(gate({ rank: 6, empId: "0002", allowlist: ["0001"] }), false);
  assert.equal(gate({ rank: 6, empId: "0001", allowlist: [] }), false);
  assert.equal(gate({ rank: 6, empId: null, allowlist: ["0001"] }), false);
});

test("a dev build always shows it", () => {
  assert.equal(evaluateArDebug({ rank: 6 }, false, true), true);
});
