"use client";

import { FormEvent, useState } from "react";

import { api } from "@/lib/client-api";

export type AiSettingsView = {
  enabled: boolean;
  prompt: string;
  maxChars: number;
  autoDelaySeconds: number;
  intervalSeconds: number;
  providers: Array<{
    index: 1 | 2;
    baseUrl: string;
    model: string;
    hasKey: boolean;
  }>;
};

type ProviderState = AiSettingsView["providers"][number] & { apiKey: string };

export function AiSettingsForm({ initial }: { initial: AiSettingsView }) {
  const [enabled, setEnabled] = useState(initial.enabled);
  const [prompt, setPrompt] = useState(initial.prompt);
  const [maxChars, setMaxChars] = useState(String(initial.maxChars));
  const [autoDelaySeconds, setAutoDelaySeconds] = useState(String(initial.autoDelaySeconds));
  const [intervalSeconds, setIntervalSeconds] = useState(String(initial.intervalSeconds));
  const [providers, setProviders] = useState<ProviderState[]>(
    initial.providers.map((provider) => ({ ...provider, apiKey: "" })),
  );
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [testing, setTesting] = useState<number | null>(null);

  function updateProvider(index: 1 | 2, field: "baseUrl" | "model" | "apiKey", value: string) {
    setProviders((current) => current.map((provider) => (
      provider.index === index ? { ...provider, [field]: value } : provider
    )));
  }

  async function save() {
    setError("");
    const result = await api<{ settings: AiSettingsView }>("/api/ai/settings", {
      method: "PUT",
      body: JSON.stringify({
        enabled,
        prompt,
        maxChars: Number(maxChars),
        autoDelaySeconds: Number(autoDelaySeconds),
        intervalSeconds: Number(intervalSeconds),
        providers: providers.map(({ index, baseUrl, model, apiKey }) => ({
          index, baseUrl, model, apiKey,
        })),
      }),
    });
    setProviders((current) => current.map((provider) => ({
      ...provider,
      apiKey: "",
      hasKey: result.settings.providers.find((item) => item.index === provider.index)?.hasKey || provider.hasKey || Boolean(provider.apiKey),
    })));
    setMessage("AI-настройки сохранены.");
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setMessage("");
    try {
      await save();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Не удалось сохранить AI-настройки.");
    } finally {
      setPending(false);
    }
  }

  async function testProvider(index: 1 | 2) {
    setTesting(index);
    setMessage("");
    setError("");
    try {
      await save();
      const created = await api<{ action: { id: string } }>("/api/ai/test", {
        method: "POST",
        body: JSON.stringify({ provider: index }),
      });
      for (let attempt = 0; attempt < 24; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 2500));
        const result = await api<{ action: { status: string; result: { reply?: string } | null; error: string | null } }>(`/api/actions/${created.action.id}`);
        if (result.action.status === "completed") {
          setMessage(`Провайдер ${index}: ${result.action.result?.reply || "связь есть"}`);
          return;
        }
        if (result.action.status === "failed") throw new Error(result.action.error || "Тест не прошёл.");
      }
      throw new Error("Бот не успел ответить на тест.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Тест не прошёл.");
    } finally {
      setTesting(null);
    }
  }

  return (
    <form className="panel ai-settings" onSubmit={submit}>
      <div className="section-heading">
        <div><p className="eyebrow">Vision-подписи</p><h2>Нейросеть</h2></div>
        <label className="switch"><input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} /> Включена</label>
      </div>
      <p className="source">Подпись создаётся заранее только тогда, когда после удаления ссылок и рекламы исходного текста не осталось.</p>
      <div className="provider-grid">
        {providers.map((provider) => (
          <fieldset key={provider.index}>
            <legend>Провайдер {provider.index}{provider.index === 2 ? " · резервный" : " · основной"}</legend>
            <label>Base URL<input aria-label={`Base URL провайдера ${provider.index}`} placeholder="https://api.example.com/v1" value={provider.baseUrl} onChange={(event) => updateProvider(provider.index, "baseUrl", event.target.value)} /></label>
            <label>Модель<input aria-label={`Модель провайдера ${provider.index}`} placeholder="vision-model" value={provider.model} onChange={(event) => updateProvider(provider.index, "model", event.target.value)} /></label>
            <label>API-ключ<input aria-label={`API-ключ провайдера ${provider.index}`} type="password" autoComplete="new-password" placeholder={provider.hasKey ? "Оставьте пустым, чтобы не менять" : "sk-..."} value={provider.apiKey} onChange={(event) => updateProvider(provider.index, "apiKey", event.target.value)} /></label>
            {provider.hasKey ? <small className="success">Ключ сохранён</small> : <small>Ключ ещё не сохранён</small>}
            <button type="button" disabled={testing !== null} onClick={() => testProvider(provider.index)}>{testing === provider.index ? "Проверяю…" : "Проверить модель"}</button>
          </fieldset>
        ))}
      </div>
      <div className="form-grid ai-prompt-grid">
        <label>Максимум символов<input aria-label="Максимум символов AI-подписи" type="number" min="40" max="300" value={maxChars} onChange={(event) => setMaxChars(event.target.value)} /></label>
        <label>Задержка после добавления (сек)<input aria-label="Задержка AI" type="number" min="30" max="3600" value={autoDelaySeconds} onChange={(event) => setAutoDelaySeconds(event.target.value)} /></label>
        <label>Пауза между генерациями (сек)<input aria-label="Пауза AI" type="number" min="10" max="600" value={intervalSeconds} onChange={(event) => setIntervalSeconds(event.target.value)} /></label>
        <label className="wide">Техническое задание<textarea aria-label="Техническое задание для нейросети" rows={7} value={prompt} onChange={(event) => setPrompt(event.target.value)} /></label>
      </div>
      <div className="actions"><button className="primary" type="submit" disabled={pending}>{pending ? "Сохраняю…" : "Сохранить AI-настройки"}</button></div>
      {message ? <p className="success">{message}</p> : null}
      {error ? <p className="error" role="alert">{error}</p> : null}
    </form>
  );
}
