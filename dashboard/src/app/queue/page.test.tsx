// @vitest-environment jsdom

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { QueueClient } from "./page";

afterEach(() => vi.restoreAllMocks());

describe("visual queue", () => {
  it("loads cards and changes only display sorting", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async () =>
      new Response(JSON.stringify({ items: [], total: 0, nextCursor: null }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    render(<QueueClient initialSearch="" />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());

    fireEvent.change(screen.getByLabelText("Сортировка"), {
      target: { value: "reactions" },
    });

    await waitFor(() =>
      expect(fetchMock.mock.calls.at(-1)?.[0]).toContain("sort=reactions"),
    );
    expect(fetchMock.mock.calls.at(-1)?.[0]).not.toContain("minReactions");
  });
});
