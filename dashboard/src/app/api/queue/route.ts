import { privateJson } from "@/lib/api";
import { query } from "@/lib/db";
import { buildQueueQuery, parseQueueFilters } from "@/lib/queue-query";

type QueueRow = {
  id: string;
  source: string;
  post_key: string;
  message_ids: string;
  media_kind: string;
  score: number | string;
  published_at: string | Date;
  status: string;
  caption_excerpt: string | null;
  views_count: number | string | null;
  reactions_count: number | string | null;
  forwards_count: number | string | null;
  preview_mime: string | null;
  error: string | null;
  total_count: number | string;
};

export async function GET(request: Request) {
  try {
    const filters = parseQueueFilters(new URL(request.url).searchParams);
    const built = buildQueueQuery(filters);
    const rows = await query<QueueRow>(built.sql, built.values);
    const total = Number(rows[0]?.total_count ?? 0);
    const items = rows.map((row) => ({
      id: row.id,
      source: row.source,
      postKey: row.post_key,
      messageIds: JSON.parse(row.message_ids || "[]"),
      mediaKind: row.media_kind,
      score: Number(row.score || 0),
      publishedAt: new Date(row.published_at).toISOString(),
      status: row.status,
      captionExcerpt: row.caption_excerpt || "",
      viewsCount: Number(row.views_count || 0),
      reactionsCount: Number(row.reactions_count || 0),
      forwardsCount: Number(row.forwards_count || 0),
      hasPreview: Boolean(row.preview_mime),
      error: row.error,
    }));
    const nextOffset = filters.offset + items.length;
    return privateJson({
      items,
      total,
      nextCursor: nextOffset < total ? String(filters.offset + filters.limit) : null,
    });
  } catch (error) {
    return privateJson(
      { error: error instanceof Error ? error.message : "Некорректный запрос." },
      { status: 400 },
    );
  }
}
