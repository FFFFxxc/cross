// @vitest-environment jsdom

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SourceManager } from "./source-manager";

afterEach(() => vi.restoreAllMocks());

describe("SourceManager", () => {
  it("adds a source with the selected news category", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ action: { id: "action-1" } }), {
        status: 202,
        headers: { "content-type": "application/json" },
      }),
    );
    render(<SourceManager sources={[]} />);

    fireEvent.change(screen.getByLabelText("Новый Telegram-источник"), {
      target: { value: "https://t.me/anime_news" },
    });
    fireEvent.change(screen.getByLabelText("Категория нового источника"), {
      target: { value: "news" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Добавить" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({
      operation: "add",
      source: "https://t.me/anime_news",
      category: "news",
    });
  });

  it("queues a category change for an existing source", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ action: { id: "action-2" } }), {
        status: 202,
        headers: { "content-type": "application/json" },
      }),
    );
    render(<SourceManager sources={[{
      peer: "anime",
      title: "Anime",
      category: "content",
      availability: "available",
      checkedAt: null,
      error: null,
    }]} />);

    fireEvent.change(screen.getByLabelText("Категория Anime"), {
      target: { value: "news" },
    });

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({
      operation: "set_category",
      source: "anime",
      category: "news",
    });
  });
});
