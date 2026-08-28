import { privateJson } from "@/lib/api";
import { aiSettingsInput } from "@/lib/actions";
import { requireSameOrigin } from "@/lib/auth";
import { encryptAiSecret } from "@/lib/ai-secrets";
import { query } from "@/lib/db";
import { getEnv } from "@/lib/env";

export const DEFAULT_AI_PROMPT = "Ты редактор русскоязычного аниме-паблика. Внимательно посмотри на изображение или кадр из видео и придумай одну короткую естественную подпись строго по его содержанию. Можно добавить лёгкую эмоцию или шутку, но нельзя выдумывать имена, названия аниме и факты, которых не видно. Не пиши ссылки, рекламу, хэштеги, призывы подписаться, кавычки и слова «нейросеть» или «изображение». Верни только готовую подпись на русском.";

const KEYS = [
  "ai_enabled", "ai_prompt", "ai_max_chars",
  "ai_provider_1_base_url", "ai_provider_1_model", "ai_provider_1_api_key",
  "ai_provider_2_base_url", "ai_provider_2_model", "ai_provider_2_api_key",
] as const;

type SettingRow = { key: string; value: string };

function safeSettings(rows: SettingRow[]) {
  const values = Object.fromEntries(rows.map((row) => [row.key, row.value]));
  return {
    enabled: values.ai_enabled === "true",
    prompt: values.ai_prompt || DEFAULT_AI_PROMPT,
    maxChars: Number(values.ai_max_chars || 140),
    providers: ([1, 2] as const).map((index) => ({
      index,
      baseUrl: values[`ai_provider_${index}_base_url`] || "",
      model: values[`ai_provider_${index}_model`] || "",
      hasKey: Boolean(values[`ai_provider_${index}_api_key`]),
    })),
  };
}

async function readRows() {
  return query<SettingRow>(
    "SELECT key, value FROM automation_settings WHERE key = ANY($1::text[])",
    [[...KEYS]],
  );
}

export async function GET() {
  return privateJson({ settings: safeSettings(await readRows()) });
}

export async function PUT(request: Request) {
  try {
    requireSameOrigin(request);
  } catch {
    return privateJson({ error: "Запрос отклонён." }, { status: 403 });
  }
  try {
    const parsed = aiSettingsInput.parse(await request.json());
    const entries: Array<[string, string]> = [
      ["ai_enabled", String(parsed.enabled)],
      ["ai_prompt", parsed.prompt],
      ["ai_max_chars", String(parsed.maxChars)],
    ];
    for (const provider of parsed.providers) {
      entries.push(
        [`ai_provider_${provider.index}_base_url`, provider.baseUrl],
        [`ai_provider_${provider.index}_model`, provider.model],
      );
      if (provider.clearKey) {
        entries.push([`ai_provider_${provider.index}_api_key`, ""]);
      } else if (provider.apiKey) {
        entries.push([
          `ai_provider_${provider.index}_api_key`,
          encryptAiSecret(provider.apiKey, getEnv().DATABASE_URL),
        ]);
      }
    }
    const values: string[] = [];
    const tuples = entries.map(([key, value]) => {
      values.push(key, value);
      return `($${values.length - 1}, $${values.length})`;
    });
    await query(
      `INSERT INTO automation_settings (key, value) VALUES ${tuples.join(", ")}
       ON CONFLICT (key) DO UPDATE SET value = excluded.value`,
      values,
    );
    await query(
      `UPDATE automation_queue
       SET ai_caption_status = 'unchecked', ai_caption_error = NULL
       WHERE status IN ('pending', 'candidate') AND ai_caption_status = 'failed'`,
    );
    return privateJson({ settings: safeSettings(await readRows()) });
  } catch (error) {
    return privateJson(
      { error: error instanceof Error ? error.message : "Некорректные AI-настройки." },
      { status: 400 },
    );
  }
}
