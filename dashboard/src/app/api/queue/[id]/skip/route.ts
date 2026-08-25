import { privateJson, unauthorized } from "@/lib/api";
import { hasSession, requireSameOrigin } from "@/lib/auth";
import { query } from "@/lib/db";

type Row = { id: string; status: string };

export async function POST(
  request: Request,
  context: { params: Promise<{ id: string }> },
) {
  if (!(await hasSession())) return unauthorized();
  try {
    requireSameOrigin(request);
  } catch {
    return privateJson({ error: "Запрос отклонён." }, { status: 403 });
  }
  const { id } = await context.params;
  const rows = await query<Row>(
    `UPDATE automation_queue SET status = 'skipped', error = NULL
     WHERE id = $1 AND status = 'pending' RETURNING id, status`,
    [id],
  );
  if (!rows[0]) return privateJson({ error: "Пост уже обработан." }, { status: 409 });
  return privateJson({ item: rows[0] });
}
