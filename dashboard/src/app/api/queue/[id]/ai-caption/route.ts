import { privateJson } from "@/lib/api";
import { requireSameOrigin } from "@/lib/auth";
import { query } from "@/lib/db";

type Row = { id: string; ai_caption_status: string };

export async function POST(
  request: Request,
  context: { params: Promise<{ id: string }> },
) {
  try {
    requireSameOrigin(request);
  } catch {
    return privateJson({ error: "Запрос отклонён." }, { status: 403 });
  }
  const { id } = await context.params;
  const rows = await query<Row>(
    `UPDATE automation_queue
     SET ai_caption = NULL, ai_caption_status = 'unchecked',
         ai_caption_provider = NULL, ai_caption_error = NULL,
         ai_caption_generated_at = NULL
     WHERE id = $1 AND status IN ('pending', 'candidate')
     RETURNING id, ai_caption_status`,
    [id],
  );
  if (!rows[0]) return privateJson({ error: "Пост уже обработан." }, { status: 409 });
  return privateJson({ item: rows[0] });
}

export async function DELETE(
  request: Request,
  context: { params: Promise<{ id: string }> },
) {
  try {
    requireSameOrigin(request);
  } catch {
    return privateJson({ error: "Запрос отклонён." }, { status: 403 });
  }
  const { id } = await context.params;
  const rows = await query<Row>(
    `UPDATE automation_queue
     SET ai_caption = NULL, ai_caption_status = 'dismissed',
         ai_caption_provider = NULL, ai_caption_error = NULL,
         ai_caption_generated_at = NULL
     WHERE id = $1 AND status IN ('pending', 'candidate')
     RETURNING id, ai_caption_status`,
    [id],
  );
  if (!rows[0]) return privateJson({ error: "Пост уже обработан." }, { status: 409 });
  return privateJson({ item: rows[0] });
}
