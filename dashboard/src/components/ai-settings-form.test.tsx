// @vitest-environment jsdom

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AiSettingsForm } from "./ai-settings-form";

afterEach(() => vi.restoreAllMocks());

const initial = {
  enabled: true,
  prompt: "Посмотри на картинку и придумай подпись",
  maxChars: 140,
  autoDelaySeconds: 90,
  intervalSeconds: 20,
  providers: [
    { index: 1 as const, baseUrl: "https://router.example/v1", model: "vision-one", hasKey: true },
    { index: 2 as const, baseUrl: "", model: "", hasKey: false },
  ],
};

describe("AiSettingsForm", () => {
  it("shows two providers without exposing stored keys and saves replacements", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ settings: initial }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    render(<AiSettingsForm initial={initial} />);
    expect(screen.getByText("Ключ сохранён")).toBeInTheDocument();
    expect(screen.getAllByLabelText(/API-ключ/)).toHaveLength(2);
    fireEvent.change(screen.getByLabelText("API-ключ провайдера 2"), {
      target: { value: "sk-backup" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить AI-настройки" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const body = JSON.parse(String(fetchMock.mock.calls[0][1]?.body));
    expect(body.providers[1].apiKey).toBe("sk-backup");
    expect(JSON.stringify(initial)).not.toContain("sk-");
  });
});
