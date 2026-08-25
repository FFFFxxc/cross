"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { api } from "@/lib/client-api";
import { AppShell } from "./app-shell";
import { QueueCard, type DashboardQueueItem } from "./queue-card";
import { QueueControls } from "./queue-controls";

type QueueResponse = {
  items: DashboardQueueItem[];
  total: number;
  nextCursor: string | null;
};

export function QueueClient({ initialSearch = "" }: { initialSearch?: string }) {
  const [search, setSearch] = useState(initialSearch);
  const [refreshKey, setRefreshKey] = useState(0);
  const [data, setData] = useState<QueueResponse>({ items: [], total: 0, nextCursor: null });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const params = useMemo(() => new URLSearchParams(search), [search]);

  useEffect(() => {
    let active = true;
    const query = new URLSearchParams(search);
    query.set("limit", "24");
    api<QueueResponse>(`/api/queue?${query.toString()}`)
      .then((result) => { if (active) setData(result); })
      .catch((reason) => {
        if (active) setError(reason instanceof Error ? reason.message : "Не удалось загрузить очередь.");
      })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [search, refreshKey]);

  const reload = useCallback(() => {
    setLoading(true);
    setError("");
    setRefreshKey((value) => value + 1);
  }, []);

  function change(name: string, value: string) {
    const next = new URLSearchParams(search);
    if (value) next.set(name, value); else next.delete(name);
    next.delete("cursor");
    const serialized = next.toString();
    setLoading(true);
    setError("");
    setSearch(serialized);
    window.history.replaceState(null, "", serialized ? `/queue?${serialized}` : "/queue");
  }

  return (
    <AppShell>
      <div className="page-heading">
        <div><p className="eyebrow">Контент</p><h1>Очередь</h1></div>
        <strong>{data.total} постов</strong>
      </div>
      <QueueControls params={params} onChange={change} />
      {loading ? <p className="notice">Загружаю очередь…</p> : null}
      {error ? <p className="notice error" role="alert">{error}</p> : null}
      {!loading && !error && data.items.length === 0 ? <p className="notice">По этим фильтрам постов нет.</p> : null}
      <div className="queue-grid">
        {data.items.map((item) => <QueueCard key={item.id} item={item} onChanged={reload} />)}
      </div>
      {data.nextCursor ? (
        <button type="button" className="load-more" onClick={() => change("cursor", data.nextCursor!)}>Следующая страница</button>
      ) : null}
    </AppShell>
  );
}
