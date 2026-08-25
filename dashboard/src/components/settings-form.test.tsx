// @vitest-environment jsdom

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SettingsForm } from "./settings-form";

afterEach(() => vi.restoreAllMocks());

describe("SettingsForm", () => {
  it("shows zero thresholds as disabled and saves validated values", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ settings: {} }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    render(
      <SettingsForm
        initial={{
          fresh_days: "7",
          min_reactions: "0",
          min_views: "0",
          signature_text: "НАШ ТГК",
          signature_url: "https://t.me/webm4ik",
        }}
      />,
    );
    expect(screen.getAllByText("без ограничения")).toHaveLength(2);
    fireEvent.change(screen.getByLabelText("Минимум реакций"), { target: { value: "150" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить настройки" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toMatchObject({
      minReactions: 150,
      freshDays: 7,
    });
  });

  it("blocks invalid signature URL in the browser", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    render(<SettingsForm initial={{ fresh_days: "7", signature_url: "https://t.me/webm4ik" }} />);
    fireEvent.change(screen.getByLabelText("Ссылка подписи"), { target: { value: "file:///secret" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить настройки" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("http");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
