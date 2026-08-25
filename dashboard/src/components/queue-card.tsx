"use client";

import Image from "next/image";

import { api } from "@/lib/client-api";
import { ActionButton } from "./action-button";

export type DashboardQueueItem = {
  id: string;
  source: string;
  postKey: string;
  messageIds: number[];
  mediaKind: string;
  score: number;
  publishedAt: string;
  status: string;
  captionExcerpt: string;
  viewsCount: number;
  reactionsCount: number;
  forwardsCount: number;
  hasPreview: boolean;
  error: string | null;
};

function number(value: number) {
  return new Intl.NumberFormat("ru-RU").format(value).replaceAll(" ", " ");
}

function pollAction(id: string, onChanged: () => void) {
  const tick = async () => {
    try {
      const result = await api<{ action: { status: string } }>(`/api/actions/${id}`);
      if (result.action.status === "completed" || result.action.status === "failed") {
        onChanged();
        return;
      }
      window.setTimeout(tick, 3000);
    } catch {
      window.setTimeout(tick, 5000);
    }
  };
  window.setTimeout(tick, 3000);
}

export function QueueCard({ item, onChanged }: { item: DashboardQueueItem; onChanged: () => void }) {
  async function publish() {
    const result = await api<{ action: { id: string } }>(`/api/queue/${item.id}/publish`, {
      method: "POST",
    });
    pollAction(result.action.id, onChanged);
  }

  async function skip() {
    await api(`/api/queue/${item.id}/skip`, { method: "POST" });
    onChanged();
  }

  async function retry() {
    const result = await api<{ action: { id: string } }>(`/api/queue/${item.id}/retry`, {
      method: "POST",
    });
    pollAction(result.action.id, onChanged);
  }

  const title = item.captionExcerpt || "Публикация без подписи";
  return (
    <article className="queue-card">
      <div className="preview">
        {item.hasPreview ? (
          <Image
            src={`/api/queue/${item.id}/preview`}
            alt={title}
            fill
            sizes="(max-width: 700px) 100vw, 33vw"
            unoptimized
          />
        ) : (
          <span>{item.mediaKind === "video" ? "Видео" : item.mediaKind === "image" ? "Изображение" : "Пост"}</span>
        )}
      </div>
      <div className="queue-body">
        <div className="badges">
          <span>{item.mediaKind}</span><span>{item.status}</span>
        </div>
        <h2>{title}</h2>
        <p className="source">{item.source}</p>
        <dl className="metrics">
          <div><dt>Просмотры</dt><dd>{number(item.viewsCount)}</dd></div>
          <div><dt>Реакции</dt><dd>{number(item.reactionsCount)}</dd></div>
          <div><dt>Репосты</dt><dd>{number(item.forwardsCount)}</dd></div>
        </dl>
        <p className="date">{new Date(item.publishedAt).toLocaleString("ru-RU")}</p>
        {item.error ? <p className="error">{item.error}</p> : null}
        <div className="actions">
          {item.status === "pending" ? (
            <>
              <ActionButton label="Опубликовать" pendingLabel="Ожидает бота" className="primary" onAction={publish} />
              <ActionButton label="Пропустить" pendingLabel="Пропускаю…" onAction={skip} />
            </>
          ) : null}
          {item.status === "failed" || item.status === "ambiguous" ? (
            <ActionButton label="Повторить" pendingLabel="Ожидает бота" onAction={retry} />
          ) : null}
        </div>
      </div>
    </article>
  );
}
