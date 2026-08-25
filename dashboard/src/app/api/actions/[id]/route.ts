import { actionJson } from "@/app/api/activity/route";
import { privateJson } from "@/lib/api";
import { query } from "@/lib/db";

export async function GET(
  _request: Request,
  context: { params: Promise<{ id: string }> },
) {
  const { id } = await context.params;
  const rows = await query<Parameters<typeof actionJson>[0]>(
    `SELECT id, action_kind, status, queue_item_id, result, error,
            created_at, claimed_at, completed_at
     FROM automation_actions WHERE id = $1`,
    [id],
  );
  if (!rows[0]) return privateJson({ error: "Действие не найдено." }, { status: 404 });
  return privateJson({ action: actionJson(rows[0]) });
}
