/**
 * TaskManager task registration for the presence foreground-service location
 * updates. MUST be imported from the root layout so the task is defined before
 * the OS delivers updates (incl. after process restarts while the FGS lives).
 */
import * as TaskManager from "expo-task-manager";
import type * as Location from "expo-location";

import { PRESENCE_TASK, presenceCycle } from "./tracker";

TaskManager.defineTask(PRESENCE_TASK, async ({ data, error }) => {
  if (error || !data) return;
  const { locations } = data as { locations?: Location.LocationObject[] };
  const loc = locations && locations.length > 0 ? locations[locations.length - 1] : null;
  await presenceCycle(loc);
});
