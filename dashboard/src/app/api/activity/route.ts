import { privateJson, unauthorized } from "@/lib/api";
import { hasSession } from "@/lib/auth";
import { query } from "@/lib/db";

type ActionRow = {
  id: string;
  action_kind: string;
  status: string;
  queue_item_id: string | null;
  result: string | null;
  error: string | null;
  created_at: string;
  claimed_at: string | null;
  completed_at: string | null;
};

function actionJson(row: ActionRow) {
  return {
    id: row.id,
    kind: row.action_kind,
    status: row.status,
    queueItemId: row.queue_item_id,
    result: row.result ? JSON.parse(row.result) : null,
    error: row.error,
    createdAt: row.created_at,
    claimedAt: row.claimed_at,
    completedAt: row.completed_at,
  };
}

export async function GET(request: Request) {
  if (!(await hasSession())) return unauthorized();
  const rawLimit = Number(new URL(request.url).searchParams.get("limit") || 50);
  const limit = Number.isInteger(rawLimit) ? Math.max(1, Math.min(100, rawLimit)) : 50;
  const rows = await query<ActionRow>(
    `SELECT id, action_kind, status, queue_item_id, result, error,
            created_at, claimed_at, completed_at
     FROM automation_actions ORDER BY created_at DESC, id DESC LIMIT $1`,
    [limit],
  );
  return privateJson({ actions: rows.map(actionJson) });
}

export { actionJson };
