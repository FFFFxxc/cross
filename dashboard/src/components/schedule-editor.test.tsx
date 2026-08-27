// @vitest-environment jsdom

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ScheduleEditor } from "./schedule-editor";

afterEach(() => vi.restoreAllMocks());

describe("ScheduleEditor", () => {
  it("edits media/source and keeps slots sorted", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ slot: {} }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    render(
      <ScheduleEditor
        initialSlots={[
          { time: "18:00", mediaKind: "any", source: null },
          { time: "08:00", mediaKind: "image", source: "anime" },
        ]}
        sources={[{ peer: "anime", title: "Anime", category: "content" }]}
      />,
    );
    const times = screen.getAllByTestId("slot-time").map((node) => node.textContent);
    expect(times).toEqual(["08:00", "18:00"]);
    fireEvent.change(screen.getAllByLabelText("Тип поста")[0], { target: { value: "video" } });
    fireEvent.click(screen.getAllByRole("button", { name: "Сохранить" })[0]);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toMatchObject({
      time: "08:00",
      mediaKind: "video",
      source: "anime",
    });
  });

  it("rejects an invalid new time", async () => {
    render(<ScheduleEditor initialSlots={[]} sources={[]} />);
    fireEvent.change(screen.getByLabelText("Новое время"), { target: { value: "29:80" } });
    fireEvent.click(screen.getByRole("button", { name: "Добавить слот" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("ЧЧ:ММ");
  });

  it("offers news slots and only news sources for them", () => {
    render(
      <ScheduleEditor
        initialSlots={[{ time: "16:00", mediaKind: "any", source: null }]}
        sources={[
          { peer: "memes", title: "Memes", category: "content" },
          { peer: "anime-news", title: "Anime News", category: "news" },
        ]}
      />,
    );

    fireEvent.change(screen.getByLabelText("Тип поста"), {
      target: { value: "news" },
    });

    expect(screen.getByLabelText("Источник слота")).toHaveTextContent("Anime News");
    expect(screen.getByLabelText("Источник слота")).not.toHaveTextContent("Memes");
  });
});
