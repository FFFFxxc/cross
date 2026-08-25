import { privateJson } from "@/lib/api";
import { query } from "@/lib/db";

type CountRow = { status: string; total: number | string };
type SettingRow = { key: string; value: string };
type ActivityRow = {
  id: string;
  action_kind: string;
  status: string;
  error: string | null;
  created_at: string;
};

function workerStatus(heartbeat: string | undefined) {
  if (!heartbeat) return { state: "offline", heartbeatAt: null };
  const age = (Date.now() - new Date(heartbeat).getTime()) / 1000;
  if (!Number.isFinite(age)) return { state: "offline", heartbeatAt: heartbeat };
  if (age <= 120) return { state: "active", heartbeatAt: heartbeat };
  if (age <= 300) return { state: "delayed", heartbeatAt: heartbeat };
  return { state: "offline", heartbeatAt: heartbeat };
}

export async function GET() {
  const [counts, settings, activity] = await Promise.all([
    query<CountRow>(
      "SELECT status, COUNT(*) AS total FROM automation_queue GROUP BY status",
    ),
    query<SettingRow>(
      `SELECT key, value FROM automation_settings
       WHERE key = ANY($1::text[])`,
      [[
        "worker_heartbeat_at",
        "scheduler_heartbeat_at",
        "scheduler_last_error",
        "fresh_days",
        "min_reactions",
        "min_views",
      ]],
    ),
    query<ActivityRow>(
      `SELECT id, action_kind, status, error, created_at
       FROM automation_actions ORDER BY created_at DESC, id DESC LIMIT 1`,
    ),
  ]);
  const values = Object.fromEntries(settings.map((item) => [item.key, item.value]));
  return privateJson({
    worker: workerStatus(values.worker_heartbeat_at),
    scheduler: {
      ...workerStatus(values.scheduler_heartbeat_at),
      lastError: values.scheduler_last_error || null,
    },
    queue: Object.fromEntries(counts.map((item) => [item.status, Number(item.total)])),
    settings: {
      freshDays: Number(values.fresh_days || 0),
      minReactions: Number(values.min_reactions || 0),
      minViews: Number(values.min_views || 0),
    },
    latestActivity: activity[0]
      ? {
          id: activity[0].id,
          kind: activity[0].action_kind,
          status: activity[0].status,
          error: activity[0].error,
          createdAt: activity[0].created_at,
        }
      : null,
  });
}
