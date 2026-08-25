import { privateJson, unauthorized } from "@/lib/api";
import { scheduleInput } from "@/lib/actions";
import { hasSession, requireSameOrigin } from "@/lib/auth";
import { query } from "@/lib/db";

export async function DELETE(
  request: Request,
  context: { params: Promise<{ time: string }> },
) {
  if (!(await hasSession())) return unauthorized();
  try {
    requireSameOrigin(request);
    const { time } = await context.params;
    scheduleInput.pick({ time: true }).parse({ time });
    const rows = await query<{ run_time: string }>(
      "DELETE FROM automation_slots WHERE run_time = $1 RETURNING run_time",
      [time],
    );
    if (!rows[0]) return privateJson({ error: "Слот не найден." }, { status: 404 });
    return privateJson({ removed: time });
  } catch (error) {
    return privateJson(
      { error: error instanceof Error ? error.message : "Некорректное время." },
      { status: 400 },
    );
  }
}
