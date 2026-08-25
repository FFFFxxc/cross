import { privateJson } from "@/lib/api";
import { requireSameOrigin } from "@/lib/auth";
import { query } from "@/lib/db";
import { scheduleInput } from "@/lib/actions";

type SlotRow = { run_time: string; media_kind: string; source: string | null };

export async function GET() {
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

export async function PUT(request: Request) {
  try {
    requireSameOrigin(request);
    const input = scheduleInput.parse(await request.json());
    await query(
      `INSERT INTO automation_slots (run_time, media_kind, source)
       VALUES ($1, $2, $3)
       ON CONFLICT (run_time) DO UPDATE SET
         media_kind = excluded.media_kind, source = excluded.source`,
      [input.time, input.mediaKind, input.source || null],
    );
    return privateJson({ slot: input });
  } catch (error) {
    return privateJson(
      { error: error instanceof Error ? error.message : "Некорректный слот." },
      { status: 400 },
    );
  }
}
