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
  metricsKnown: boolean;
  hasPreview: boolean;
  aiCaption: string | null;
  aiCaptionStatus: string;
  aiCaptionProvider: string | null;
  aiCaptionError: string | null;
  error: string | null;
};

function number(value: number) {
  return new Intl.NumberFormat("ru-RU").format(value).replaceAll(" ", " ");
}

function metric(value: number, known: boolean) {
  return known ? number(value) : "Нет данных";
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

  async function regenerateCaption() {
    await api(`/api/queue/${item.id}/ai-caption`, { method: "POST" });
    onChanged();
  }

  const title = item.captionExcerpt || item.aiCaption || "Публикация без подписи";
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
        {item.aiCaption ? (
          <div className="ai-caption"><strong>AI-подпись</strong><p>{item.aiCaption}</p><small>{item.aiCaptionProvider}</small></div>
        ) : item.aiCaptionStatus === "processing" ? (
          <p className="ai-caption-status">Нейросеть готовит подпись…</p>
        ) : item.aiCaptionError ? (
          <p className="error">AI: {item.aiCaptionError}</p>
        ) : null}
        <dl className="metrics">
          <div><dt>Просмотры</dt><dd>{metric(item.viewsCount, item.metricsKnown)}</dd></div>
          <div><dt>Реакции</dt><dd>{metric(item.reactionsCount, item.metricsKnown)}</dd></div>
          <div><dt>Репосты</dt><dd>{metric(item.forwardsCount, item.metricsKnown)}</dd></div>
        </dl>
        <p className="date">{new Date(item.publishedAt).toLocaleString("ru-RU")}</p>
        {item.error ? <p className="error">{item.error}</p> : null}
        <div className="actions">
          {item.status === "pending" || item.status === "candidate" ? (
            <>
              <ActionButton label="Опубликовать" pendingLabel="Ожидает бота" className="primary" onAction={publish} />
              <ActionButton label="Пропустить" pendingLabel="Пропускаю…" onAction={skip} />
              <ActionButton label={item.aiCaption ? "Сгенерировать заново" : "Сгенерировать подпись"} pendingLabel="Ставлю в очередь…" onAction={regenerateCaption} />
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
