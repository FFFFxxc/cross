import { AppShell } from "@/components/app-shell";
import { SettingsLoader } from "@/components/settings-loader";
import { requireSession } from "@/lib/auth";

export default async function SettingsPage() {
  await requireSession();
  return (
    <AppShell>
      <div className="page-heading"><div><p className="eyebrow">Автоматика</p><h1>Настройки</h1></div></div>
      <p className="notice">Порог влияет только на автоматические публикации. Сортировка очереди — только на отображение.</p>
      <SettingsLoader />
    </AppShell>
  );
}
