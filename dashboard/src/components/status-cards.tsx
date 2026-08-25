type Overview = {
  worker: { state: string; heartbeatAt: string | null };
  scheduler: { state: string; heartbeatAt: string | null; lastError: string | null };
  queue: Record<string, number>;
  settings: { freshDays: number; minReactions: number; minViews: number };
};

export function StatusCards({ overview }: { overview: Overview }) {
  const labels = { active: "Работает", delayed: "Задержка", offline: "Не в сети" } as Record<string, string>;
  return (
    <div className="status-grid">
      <article className="status-card">
        <span className={`status-dot ${overview.worker.state}`} />
        <p>Render-воркер</p><strong>{labels[overview.worker.state] || overview.worker.state}</strong>
      </article>
      <article className="status-card">
        <span className={`status-dot ${overview.scheduler.state}`} />
        <p>Расписание</p><strong>{labels[overview.scheduler.state] || overview.scheduler.state}</strong>
        {overview.scheduler.lastError ? <small title={overview.scheduler.lastError}>Последняя ошибка сохранена</small> : null}
      </article>
      <article className="status-card"><p>В очереди</p><strong>{overview.queue.pending || 0}</strong></article>
      <article className="status-card"><p>Опубликовано</p><strong>{overview.queue.published || 0}</strong></article>
      <article className="status-card"><p>Окно свежести</p><strong>{overview.settings.freshDays || 0} дн.</strong></article>
      <article className="status-card"><p>Мин. реакций</p><strong>{overview.settings.minReactions || "Нет"}</strong></article>
      <article className="status-card"><p>Мин. просмотров</p><strong>{overview.settings.minViews || "Нет"}</strong></article>
    </div>
  );
}
