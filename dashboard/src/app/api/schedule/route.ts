import { privateJson, unauthorized } from "@/lib/api";
import { hasSession } from "@/lib/auth";
import { query } from "@/lib/db";

type SlotRow = { run_time: string; media_kind: string; source: string | null };

export async function GET() {
  if (!(await hasSession())) return unauthorized();
  const slots = await query<SlotRow>(
    "SELECT run_time, media_kind, source FROM automation_slots ORDER BY run_time",
  );
  return privateJson({
    timezone: "Europe/Moscow",
    slots: slots.map((slot) => ({
      time: slot.run_time,
      mediaKind: slot.media_kind,
      source: slot.source,
    })),
  });
}
