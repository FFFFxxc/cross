"use client";

import { FormEvent, useState } from "react";

import { api } from "@/lib/client-api";

export type DashboardSource = {
  peer: string;
  title: string;
  availability: string;
  checkedAt: string | null;
  error: string | null;
};

export function SourceManager({ sources }: { sources: DashboardSource[] }) {
  const [source, setSource] = useState("");
  const [status, setStatus] = useState("");
  const [pending, setPending] = useState(false);

  async function action(operation: "add" | "remove", value: string) {
    setPending(true);
    setStatus("");
    try {
      const result = await api<{ action: { id: string } }>("/api/sources/actions", {
        method: "POST",
        body: JSON.stringify({ operation, source: value }),
      });
      setStatus(`Действие ${result.action.id} ожидает Render-бота.`);
      if (operation === "add") setSource("");
    } catch (reason) {
      setStatus(reason instanceof Error ? reason.message : "Ошибка источника.");
    } finally {
      setPending(false);
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    void action("add", source);
  }

  return (
    <section className="panel">
      <form className="inline-form" onSubmit={submit}>
        <label>Новый Telegram-источник<input placeholder="https://t.me/channel" value={source} onChange={(event) => setSource(event.target.value)} required /></label>
        <button className="primary" disabled={pending}>Добавить</button>
      </form>
      {status ? <p>{status}</p> : null}
      <div className="source-list">
        {sources.map((item) => (
          <article key={item.peer} className="source-row">
            <div><strong>{item.title}</strong><p>{item.peer} · {item.availability}</p>{item.error ? <small className="error">{item.error}</small> : null}</div>
            <button type="button" onClick={() => {
              if (window.confirm("Удалить источник? Уже собранные посты останутся в очереди и истории.")) void action("remove", item.peer);
            }}>Удалить</button>
          </article>
        ))}
      </div>
    </section>
  );
}
