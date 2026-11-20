// @vitest-environment jsdom

import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AiSettingsForm } from "./ai-settings-form";

afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

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
  it("shows each vision check separately, including a failed model", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify({ settings: initial })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ action: { id: "ai-check" } })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ action: { status: "completed", error: null, result: {
        reply: "Работают: 1 из 2",
        models: [{ model: "vision-one", ok: false, error: "HTTP 429" }, { model: "backup", ok: true }],
      } } })));
    render(<AiSettingsForm initial={initial} />);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Проверить профиль 1" })); });
    await act(async () => { await vi.advanceTimersByTimeAsync(2500); });
    const results = within(screen.getByRole("list", { name: "Проверка профиля 1" }));
    expect(results.getByText("HTTP 429")).toBeInTheDocument();
    expect(results.getByText("Работает с изображениями")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenLastCalledWith("/api/actions/ai-check", expect.anything());
  });
  it("adds, reorders and removes a backup, and saves displayed order", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ settings: initial })));
    render(<AiSettingsForm initial={initial} />);
    const profile = within(screen.getByRole("group", { name: /Профиль 1/ }));
    fireEvent.click(profile.getByRole("button", { name: "Добавить запасную модель" }));
    fireEvent.change(profile.getByLabelText("Модель 2 профиля 1"), { target: { value: "vision-two" } });
    fireEvent.click(profile.getByRole("button", { name: "Добавить запасную модель" }));
    expect(profile.getByRole("button", { name: "Добавить запасную модель" })).toBeDisabled();
    fireEvent.click(profile.getByRole("button", { name: "Удалить модель 3 профиля 1" }));
    fireEvent.click(profile.getByRole("button", { name: "Поднять модель 2 профиля 1" }));
    fireEvent.click(screen.getByRole("button", { name: "Сохранить AI-настройки" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const body = JSON.parse(String(fetchMock.mock.calls[0][1]?.body));
    expect(body.providers[0].models).toEqual(["vision-two", "vision-one"]);
    expect(body.providers[0].apiKey).toBe("");
  });
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
