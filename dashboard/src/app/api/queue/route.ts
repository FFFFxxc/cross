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
  metrics_known: boolean | number | string | null;
  preview_mime: string | null;
  ai_caption: string | null;
  ai_caption_status: string | null;
  ai_caption_provider: string | null;
  ai_caption_error: string | null;
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
      metricsKnown: Boolean(Number(row.metrics_known || 0)),
      hasPreview: Boolean(row.preview_mime),
      aiCaption: row.ai_caption || null,
      aiCaptionStatus: row.ai_caption_status || "unchecked",
      aiCaptionProvider: row.ai_caption_provider || null,
      aiCaptionError: row.ai_caption_error || null,
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
