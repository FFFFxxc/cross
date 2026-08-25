import { AppShell } from "@/components/app-shell";
import { SettingsForm } from "@/components/settings-form";
import { requireSession } from "@/lib/auth";
import { query } from "@/lib/db";

type Setting = { key: string; value: string };

export default async function SettingsPage() {
  await requireSession();
  const rows = await query<Setting>(
    `SELECT key, value FROM automation_settings
     WHERE key = ANY($1::text[])`,
    [["fresh_days", "min_reactions", "min_views", "signature_text", "signature_url"]],
  );
  return (
    <AppShell>
      <div className="page-heading"><div><p className="eyebrow">Автоматика</p><h1>Настройки</h1></div></div>
      <p className="notice">Порог влияет только на автоматические публикации. Сортировка очереди — только на отображение.</p>
      <SettingsForm initial={Object.fromEntries(rows.map((row) => [row.key, row.value]))} />
    </AppShell>
  );
}
