import { AppShell } from "@/components/app-shell";
import { ScanForm } from "@/components/scan-form";
import { SourceManager, type DashboardSource } from "@/components/source-manager";
import { query } from "@/lib/db";

type Row = {
  peer: string;
  title: string;
  availability: string;
  checked_at: string | null;
  error: string | null;
};

export default async function SourcesPage() {
  const rows = await query<Row>(
    "SELECT peer, title, availability, checked_at, error FROM automation_sources ORDER BY added_at, peer",
  );
  const sources: DashboardSource[] = rows.map((row) => ({
    peer: row.peer,
    title: row.title,
    availability: row.availability,
    checkedAt: row.checked_at,
    error: row.error,
  }));
  return (
    <AppShell>
      <div className="page-heading"><div><p className="eyebrow">Telegram</p><h1>Источники</h1></div></div>
      <SourceManager sources={sources} />
      <ScanForm sources={sources} />
    </AppShell>
  );
}
