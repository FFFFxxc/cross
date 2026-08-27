"use client";

import { FormEvent, useState } from "react";

import { api } from "@/lib/client-api";

export type DashboardSource = {
  peer: string;
  title: string;
  category: "content" | "news";
  availability: string;
  checkedAt: string | null;
  error: string | null;
};

export function SourceManager({ sources }: { sources: DashboardSource[] }) {
  const [source, setSource] = useState("");
  const [category, setCategory] = useState<"content" | "news">("content");
  const [categories, setCategories] = useState<Record<string, "content" | "news">>(
    () => Object.fromEntries(sources.map((item) => [item.peer, item.category])),
  );
  const [status, setStatus] = useState("");
  const [pending, setPending] = useState(false);

  async function action(
    operation: "add" | "remove" | "set_category",
    value: string,
    selectedCategory: "content" | "news" = "content",
  ) {
    setPending(true);
    setStatus("");
    try {
      const result = await api<{ action: { id: string } }>("/api/sources/actions", {
        method: "POST",
        body: JSON.stringify({
          operation,
          source: value,
          ...(operation === "remove" ? {} : { category: selectedCategory }),
        }),
      });
      setStatus(`Действие ${result.action.id} ожидает Render-бота.`);
      if (operation === "add") setSource("");
      if (operation === "set_category") {
        setCategories((current) => ({ ...current, [value]: selectedCategory }));
      }
    } catch (reason) {
      setStatus(reason instanceof Error ? reason.message : "Ошибка источника.");
    } finally {
      setPending(false);
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    void action("add", source, category);
  }

  return (
    <section className="panel">
      <form className="inline-form" onSubmit={submit}>
        <label>Новый Telegram-источник<input placeholder="https://t.me/channel" value={source} onChange={(event) => setSource(event.target.value)} required /></label>
        <label>Категория нового источника<select value={category} onChange={(event) => setCategory(event.target.value as "content" | "news")}><option value="content">Обычный</option><option value="news">Новости</option></select></label>
        <button className="primary" disabled={pending}>Добавить</button>
      </form>
      {status ? <p>{status}</p> : null}
      <div className="source-list">
        {sources.map((item) => (
          <article key={item.peer} className="source-row">
            <div><strong>{item.title}</strong><p>{item.peer} · {item.availability} · <span className={`badge-text ${categories[item.peer] === "news" ? "news" : ""}`}>{categories[item.peer] === "news" ? "Новости" : "Обычный"}</span></p>{item.error ? <small className="error">{item.error}</small> : null}</div>
            <label>Категория {item.title}<select value={categories[item.peer]} onChange={(event) => void action("set_category", item.peer, event.target.value as "content" | "news")}><option value="content">Обычный</option><option value="news">Новости</option></select></label>
            <button type="button" onClick={() => {
              if (window.confirm("Удалить источник? Уже собранные посты останутся в очереди и истории.")) void action("remove", item.peer);
            }}>Удалить</button>
          </article>
        ))}
      </div>
    </section>
  );
}
