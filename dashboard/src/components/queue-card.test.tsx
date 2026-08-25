// @vitest-environment jsdom

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { QueueCard } from "./queue-card";

const item = {
  id: "item-1",
  source: "animeworldmem",
  postKey: "message:1",
  messageIds: [1],
  mediaKind: "video",
  score: 900,
  publishedAt: "2026-08-25T12:00:00.000Z",
  status: "pending",
  captionExcerpt: "Сильный аниме-пост",
  viewsCount: 12_500,
  reactionsCount: 430,
  forwardsCount: 55,
  metricsKnown: true,
  hasPreview: true,
  error: null,
};

afterEach(() => vi.restoreAllMocks());

describe("QueueCard", () => {
  it("renders preview, caption, metrics, source and actions", () => {
    render(<QueueCard item={item} onChanged={vi.fn()} />);
    expect(screen.getByRole("img", { name: /сильный аниме-пост/i })).toHaveAttribute(
      "src",
      expect.stringContaining("/api/queue/item-1/preview"),
    );
    expect(screen.getByText("Сильный аниме-пост")).toBeInTheDocument();
    expect(screen.getByText("12 500")).toBeInTheDocument();
    expect(screen.getByText("430")).toBeInTheDocument();
    expect(screen.getByText("animeworldmem")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Опубликовать" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Пропустить" })).toBeEnabled();
  });

  it("offers the same manual actions for a candidate", () => {
    render(<QueueCard item={{ ...item, status: "candidate" }} onChanged={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Опубликовать" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Пропустить" })).toBeEnabled();
  });

  it("disables publish immediately and shows worker wait state", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ action: { id: "action-1", status: "pending" } }), {
        status: 202,
        headers: { "content-type": "application/json" },
      }),
    );
    render(<QueueCard item={item} onChanged={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Опубликовать" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Ожидает бота" })).toBeDisabled());
  });

  it("uses a placeholder when preview is absent", () => {
    render(<QueueCard item={{ ...item, hasPreview: false }} onChanged={vi.fn()} />);
    expect(screen.getByText("Видео")).toBeInTheDocument();
  });
});
