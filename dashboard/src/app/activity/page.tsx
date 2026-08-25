import { AppShell } from "@/components/app-shell";
import { ActivityList } from "@/components/activity-list";
import { query } from "@/lib/db";

type Row = {
  id: string;
  action_kind: string;
  status: string;
  queue_item_id: string | null;
  result: string | null;
  error: string | null;
  created_at: string;
  completed_at: string | null;
};

export default async function ActivityPage() {
  const rows = await query<Row>(
    `SELECT id, action_kind, status, queue_item_id, result, error, created_at, completed_at
     FROM automation_actions ORDER BY created_at DESC, id DESC LIMIT 100`,
  );
  return (
    <AppShell>
      <div className="page-heading"><div><p className="eyebrow">Журнал</p><h1>События</h1></div></div>
      <ActivityList actions={rows.map((row) => ({
        id: row.id,
        kind: row.action_kind,
        status: row.status,
        queueItemId: row.queue_item_id,
        result: row.result ? JSON.parse(row.result) : null,
        error: row.error,
        createdAt: row.created_at,
        completedAt: row.completed_at,
      }))} />
    </AppShell>
  );
}
