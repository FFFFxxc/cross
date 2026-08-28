import type {
  MediaKind,
  QueueFilters,
  QueueSort,
  QueueStatus,
} from "./types";

const SORT_SQL: Record<QueueSort, string> = {
  newest: "published_at DESC, id DESC",
  reactions: "reactions_count DESC, published_at DESC",
  views: "views_count DESC, published_at DESC",
  score: "score DESC, published_at DESC",
};

const SORTS = new Set(Object.keys(SORT_SQL));
const MEDIA = new Set<MediaKind>(["any", "video", "image"]);
const STATUSES = new Set<QueueStatus>([
  "pending",
  "processing",
  "published",
  "failed",
  "ambiguous",
  "skipped",
  "expired",
  "candidate",
]);

function integer(value: string | null, fallback: number): number {
  if (value === null || value === "") return fallback;
  if (!/^\d+$/.test(value)) throw new Error("Ожидалось целое число.");
  return Number(value);
}

export function parseQueueFilters(params: URLSearchParams): QueueFilters {
  const sort = params.get("sort") || "score";
  const media = params.get("media") || "any";
  const status = params.get("status") || "pending";
  if (!SORTS.has(sort)) throw new Error("Неизвестная сортировка.");
  if (!MEDIA.has(media as MediaKind)) throw new Error("Неизвестный тип медиа.");
  if (!STATUSES.has(status as QueueStatus)) throw new Error("Неизвестный статус.");
  const source = params.get("source")?.trim() || undefined;
  if (source && source.length > 200) throw new Error("Источник слишком длинный.");
  return {
    sort: sort as QueueSort,
    source,
    media: media as MediaKind,
    status: status as QueueStatus,
    minReactions: integer(params.get("minReactions"), 0),
    minViews: integer(params.get("minViews"), 0),
    limit: Math.max(10, Math.min(60, integer(params.get("limit"), 24))),
    offset: integer(params.get("cursor"), 0),
  };
}

export function buildQueueQuery(filters: QueueFilters): {
  sql: string;
  values: unknown[];
} {
  const clauses: string[] = [];
  const values: unknown[] = [];
  const add = (clause: string, value: unknown) => {
    values.push(value);
    clauses.push(clause.replace("?", `$${values.length}`));
  };
  add("status = ?", filters.status);
  if (filters.source) add("source = ?", filters.source);
  if (filters.media !== "any") add("media_kind = ?", filters.media);
  add("COALESCE(reactions_count, 0) >= ?", filters.minReactions);
  add("COALESCE(views_count, 0) >= ?", filters.minViews);
  values.push(filters.limit, filters.offset);
  const limitParam = `$${values.length - 1}`;
  const offsetParam = `$${values.length}`;
  return {
    sql: `
      SELECT id, source, post_key, message_ids, media_kind, score,
             published_at, status, caption_excerpt, views_count,
             reactions_count, forwards_count, metrics_known, preview_mime, error,
             ai_caption, ai_caption_status, ai_caption_provider, ai_caption_error,
             COUNT(*) OVER() AS total_count
      FROM automation_queue
      WHERE ${clauses.join(" AND ")}
      ORDER BY ${SORT_SQL[filters.sort]}
      LIMIT ${limitParam} OFFSET ${offsetParam}
    `,
    values,
  };
}
