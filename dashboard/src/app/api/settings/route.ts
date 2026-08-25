import { privateJson } from "@/lib/api";
import { requireSameOrigin } from "@/lib/auth";
import { settingsInput } from "@/lib/actions";
import { query } from "@/lib/db";

export const SETTING_KEYS = [
  "fresh_days",
  "min_reactions",
  "min_views",
  "signature_text",
  "signature_url",
] as const;

type SettingRow = { key: string; value: string };

export async function GET() {
  const settings = await query<SettingRow>(
    "SELECT key, value FROM automation_settings WHERE key = ANY($1::text[])",
    [[...SETTING_KEYS]],
  );
  return privateJson({
    settings: Object.fromEntries(settings.map((item) => [item.key, item.value])),
  });
}

const SETTING_FIELDS = {
  freshDays: "fresh_days",
  minReactions: "min_reactions",
  minViews: "min_views",
  signatureText: "signature_text",
  signatureUrl: "signature_url",
} as const;

export async function PUT(request: Request) {
  try {
    requireSameOrigin(request);
  } catch {
    return privateJson({ error: "Запрос отклонён." }, { status: 403 });
  }
  try {
    const parsed = settingsInput.parse(await request.json());
    const entries = Object.entries(parsed).map(([field, value]) => [
      SETTING_FIELDS[field as keyof typeof SETTING_FIELDS],
      String(value),
    ]);
    const values: unknown[] = [];
    const rows = entries.map(([key, value]) => {
      values.push(key, value);
      return `($${values.length - 1}, $${values.length})`;
    });
    await query(
      `INSERT INTO automation_settings (key, value) VALUES ${rows.join(", ")}
       ON CONFLICT (key) DO UPDATE SET value = excluded.value`,
      values,
    );
    return privateJson({ settings: Object.fromEntries(entries) });
  } catch (error) {
    return privateJson(
      { error: error instanceof Error ? error.message : "Некорректные настройки." },
      { status: 400 },
    );
  }
}
