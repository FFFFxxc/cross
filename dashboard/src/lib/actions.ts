import { randomUUID } from "node:crypto";
import { z } from "zod";

import { query } from "./db";

const httpUrl = z.string().url().refine((value) => {
  const protocol = new URL(value).protocol;
  return protocol === "http:" || protocol === "https:";
}, "Разрешены только HTTP/HTTPS ссылки.");

const telegramSource = z.string().trim().min(2).max(200).refine(
  (value) =>
    /^@?[A-Za-z0-9_]{4,}$/.test(value) ||
    /^https?:\/\/(?:www\.)?t\.me\/(?:\+|joinchat\/)?[^\s/]+\/?(?:\?[^\s]*)?$/i.test(value),
  "Укажите ссылку t.me или имя Telegram-канала.",
);

export const sourceInput = z.object({
  operation: z.enum(["add", "remove"]),
  source: telegramSource,
});

const dateText = z.string().regex(/^\d{4}-\d{2}-\d{2}$/, "Дата: ГГГГ-ММ-ДД.");

export const scanInput = z.object({
  count: z.number().int().min(1).max(1000),
  source: telegramSource.optional(),
  mediaKind: z.enum(["any", "video", "image"]).default("any"),
  start: dateText.optional(),
  end: dateText.optional(),
}).refine((value) => !value.start || !value.end || value.start <= value.end, {
  message: "Дата окончания должна быть не раньше начала.",
});

export const scheduleInput = z.object({
  time: z.string().regex(/^(?:[01]\d|2[0-3]):[0-5]\d$/, "Время: ЧЧ:ММ."),
  mediaKind: z.enum(["any", "video", "image"]),
  source: z.string().trim().min(1).max(200).nullable().optional(),
});

export const settingsInput = z.object({
  freshDays: z.number().int().min(1).max(90).optional(),
  minReactions: z.number().int().min(0).max(1_000_000).optional(),
  minViews: z.number().int().min(0).max(1_000_000).optional(),
  signatureText: z.string().trim().min(1).max(200).optional(),
  signatureUrl: httpUrl.optional(),
}).refine((value) => Object.keys(value).length > 0, "Нет настроек для сохранения.");

export type ActionRow = {
  id: string;
  action_kind: string;
  status: string;
  queue_item_id: string | null;
  created_at: string;
};

export async function createAction(
  kind: string,
  payload: Record<string, unknown>,
  queueItemId: string | null = null,
): Promise<ActionRow> {
  const id = randomUUID().replaceAll("-", "").slice(0, 16);
  try {
    const rows = await query<ActionRow>(
      `INSERT INTO automation_actions
         (id, action_kind, payload, status, queue_item_id, created_at)
       VALUES ($1, $2, $3, 'pending', $4, $5)
       RETURNING id, action_kind, status, queue_item_id, created_at`,
      [id, kind, JSON.stringify(payload), queueItemId, new Date().toISOString()],
    );
    return rows[0];
  } catch (error) {
    if (
      kind === "publish_now" &&
      queueItemId &&
      typeof error === "object" &&
      error !== null &&
      "code" in error &&
      error.code === "23505"
    ) {
      const rows = await query<ActionRow>(
        `SELECT id, action_kind, status, queue_item_id, created_at
         FROM automation_actions
         WHERE action_kind = 'publish_now' AND queue_item_id = $1
           AND status IN ('pending', 'processing')
         ORDER BY created_at DESC LIMIT 1`,
        [queueItemId],
      );
      if (rows[0]) return rows[0];
    }
    throw error;
  }
}
