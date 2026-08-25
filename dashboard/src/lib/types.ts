export type QueueSort = "newest" | "reactions" | "views" | "score";
export type MediaKind = "any" | "video" | "image";
export type QueueStatus =
  | "pending"
  | "processing"
  | "published"
  | "failed"
  | "ambiguous"
  | "skipped"
  | "expired"
  | "candidate";

export interface QueueFilters {
  sort: QueueSort;
  source?: string;
  media: MediaKind;
  status: QueueStatus;
  minReactions: number;
  minViews: number;
  limit: number;
  offset: number;
}
