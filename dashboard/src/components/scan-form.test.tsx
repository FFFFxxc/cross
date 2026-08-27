// @vitest-environment jsdom

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ScanForm } from "./scan-form";

afterEach(() => vi.restoreAllMocks());

describe("ScanForm", () => {
  it("collects news only from news sources", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ action: { id: "scan-1" } }), {
        status: 202,
        headers: { "content-type": "application/json" },
      }),
    );
    render(<ScanForm sources={[
      {
        peer: "memes",
        title: "Memes",
        category: "content",
        availability: "available",
        checkedAt: null,
        error: null,
      },
      {
        peer: "anime-news",
        title: "Anime News",
        category: "news",
        availability: "available",
        checkedAt: null,
        error: null,
      },
    ]} />);

    fireEvent.change(screen.getByLabelText("Тип сбора"), {
      target: { value: "news" },
    });
    const source = screen.getByLabelText("Источник сбора");
    expect(source).toHaveTextContent("Anime News");
    expect(source).not.toHaveTextContent("Memes");
    fireEvent.change(source, { target: { value: "anime-news" } });
    fireEvent.click(screen.getByRole("button", { name: "Собрать посты" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toMatchObject({
      source: "anime-news",
      mediaKind: "news",
    });
  });
});
