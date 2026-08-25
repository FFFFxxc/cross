import { privateJson, unauthorized } from "@/lib/api";
import { hasSession } from "@/lib/auth";
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
  if (!(await hasSession())) return unauthorized();
  const settings = await query<SettingRow>(
    "SELECT key, value FROM automation_settings WHERE key = ANY($1::text[])",
    [[...SETTING_KEYS]],
  );
  return privateJson({
    settings: Object.fromEntries(settings.map((item) => [item.key, item.value])),
  });
}
