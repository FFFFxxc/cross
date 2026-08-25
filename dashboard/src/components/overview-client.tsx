"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { api } from "@/lib/client-api";
import { AppShell } from "./app-shell";
import { StatusCards } from "./status-cards";

type Overview = Parameters<typeof StatusCards>[0]["overview"] & {
  latestActivity: { kind: string; status: string; createdAt: string; error: string | null } | null;
};

export function OverviewClient() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api<Overview>("/api/overview").then(setOverview).catch((reason) => setError(reason.message));
  }, []);
  return (
    <AppShell>
      <div className="hero">
        <div><p className="eyebrow">Автопостинг</p><h1>Всё важное — на одном экране</h1><p>Очередь Telegram → MAX, без команд в чате.</p></div>
        <Link href="/queue" className="button primary">Открыть очередь</Link>
      </div>
      {error ? <p role="alert" className="notice error">{error}</p> : null}
      {overview ? <StatusCards overview={overview} /> : <p className="notice">Проверяю состояние…</p>}
      {overview?.latestActivity ? (
        <section className="panel"><h2>Последнее действие</h2><p>{overview.latestActivity.kind} · {overview.latestActivity.status}</p>{overview.latestActivity.error ? <p className="error">{overview.latestActivity.error}</p> : null}</section>
      ) : null}
    </AppShell>
  );
}
