"use client";

import { FormEvent, useState } from "react";

import { api } from "@/lib/client-api";
import type { DashboardSource } from "./source-manager";

export function ScanForm({ sources }: { sources: DashboardSource[] }) {
  const [pending, setPending] = useState(false);
  const [status, setStatus] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setStatus("");
    const form = new FormData(event.currentTarget);
    try {
      const result = await api<{ action: { id: string } }>("/api/scans", {
        method: "POST",
        body: JSON.stringify({
          count: Number(form.get("count")),
          source: form.get("source") || undefined,
          mediaKind: form.get("mediaKind"),
          start: form.get("start") || undefined,
          end: form.get("end") || undefined,
        }),
      });
      setStatus(`Сбор ${result.action.id} поставлен в очередь.`);
    } catch (reason) {
      setStatus(reason instanceof Error ? reason.message : "Не удалось запустить сбор.");
    } finally {
      setPending(false);
    }
  }
  return (
    <section className="panel">
      <h2>Наполнить очередь</h2>
      <form className="form-grid" onSubmit={submit}>
        <label>Количество<input name="count" type="number" min="1" max="1000" defaultValue="50" /></label>
        <label>Источник<select name="source"><option value="">Все</option>{sources.map((source) => <option key={source.peer} value={source.peer}>{source.title}</option>)}</select></label>
        <label>Тип<select name="mediaKind" defaultValue="any"><option value="any">Любой</option><option value="video">Видео</option><option value="image">Картинка</option></select></label>
        <label>С даты<input name="start" type="date" /></label>
        <label>По дату<input name="end" type="date" /></label>
        <button className="primary" disabled={pending}>{pending ? "Запускаю…" : "Собрать посты"}</button>
      </form>
      {status ? <p>{status}</p> : null}
    </section>
  );
}
