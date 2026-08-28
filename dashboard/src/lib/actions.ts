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
  operation: z.enum(["add", "remove", "set_category"]),
  source: telegramSource,
  category: z.enum(["content", "news"]).default("content"),
});

const dateText = z.string().regex(/^\d{4}-\d{2}-\d{2}$/, "Дата: ГГГГ-ММ-ДД.");

export const scanInput = z.object({
  count: z.number().int().min(1).max(1000),
  source: telegramSource.optional(),
  mediaKind: z.enum(["any", "video", "image", "news"]).default("any"),
  start: dateText.optional(),
  end: dateText.optional(),
}).refine((value) => !value.start || !value.end || value.start <= value.end, {
  message: "Дата окончания должна быть не раньше начала.",
});

export const scheduleInput = z.object({
  time: z.string().regex(/^(?:[01]\d|2[0-3]):[0-5]\d$/, "Время: ЧЧ:ММ."),
  mediaKind: z.enum(["any", "video", "image", "news"]),
  source: z.string().trim().min(1).max(200).nullable().optional(),
});

export const settingsInput = z.object({
  freshDays: z.number().int().min(1).max(90).optional(),
  newsFreshDays: z.number().int().min(1).max(7).optional(),
  minReactions: z.number().int().min(0).max(1_000_000).optional(),
  minViews: z.number().int().min(0).max(1_000_000).optional(),
  signatureText: z.string().trim().min(1).max(200).optional(),
  signatureUrl: httpUrl.optional(),
}).refine((value) => Object.keys(value).length > 0, "Нет настроек для сохранения.");

const httpsBaseUrl = z.string().trim().max(500).refine((value) => {
  if (!value) return true;
  try {
    const parsed = new URL(value);
    return parsed.protocol === "https:" && Boolean(parsed.hostname) && !parsed.username && !parsed.password;
  } catch {
    return false;
  }
}, "Base URL должен быть публичным HTTPS-адресом.");

const aiProviderInput = z.object({
  index: z.union([z.literal(1), z.literal(2)]),
  baseUrl: httpsBaseUrl,
  model: z.string().trim().max(200),
  apiKey: z.string().trim().max(1000).optional().default(""),
  clearKey: z.boolean().optional().default(false),
});

export const aiSettingsInput = z.object({
  enabled: z.boolean(),
  prompt: z.string().trim().min(5).max(3000),
  maxChars: z.number().int().min(40).max(300),
  providers: z.array(aiProviderInput).length(2),
}).refine(
  (value) => new Set(value.providers.map((provider) => provider.index)).size === 2,
  "Нужны настройки провайдеров 1 и 2.",
).refine(
  (value) => value.providers.every((provider) => (!provider.baseUrl && !provider.model) || (provider.baseUrl && provider.model)),
  "Для провайдера заполните одновременно Base URL и модель.",
);

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
