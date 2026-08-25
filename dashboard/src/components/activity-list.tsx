type Activity = {
  id: string;
  kind: string;
  status: string;
  queueItemId: string | null;
  result: Record<string, unknown> | null;
  error: string | null;
  createdAt: string;
  completedAt: string | null;
};

export function ActivityList({ actions }: { actions: Activity[] }) {
  if (!actions.length) return <p className="notice">Действий пока нет.</p>;
  return (
    <div className="activity-list">
      {actions.map((action) => (
        <article className="panel activity-row" key={action.id}>
          <div><strong>{action.kind}</strong><p>{action.id}{action.queueItemId ? ` · ${action.queueItemId}` : ""}</p></div>
          <div><span className="badge-text">{action.status}</span><p>{new Date(action.createdAt).toLocaleString("ru-RU")}</p></div>
          {action.result ? <code>{JSON.stringify(action.result)}</code> : null}
          {action.error ? <p className="error">{action.error}</p> : null}
        </article>
      ))}
    </div>
  );
}
