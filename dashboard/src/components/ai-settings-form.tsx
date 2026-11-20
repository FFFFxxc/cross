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
    models?: string[];
    hasKey: boolean;
  }>;
};

type ProviderState = AiSettingsView["providers"][number] & { apiKey: string; models: string[] };
type ModelCheck = { model: string; ok: boolean; error?: string };
const MAX_MODELS = 3;

function providerState(provider: AiSettingsView["providers"][number]): ProviderState {
  const models = provider.models ?? (provider.model ? [provider.model] : []);
  return { ...provider, apiKey: "", models: models.length ? models : [""] };
}

export function AiSettingsForm({ initial }: { initial: AiSettingsView }) {
  const [enabled, setEnabled] = useState(initial.enabled);
  const [prompt, setPrompt] = useState(initial.prompt);
  const [maxChars, setMaxChars] = useState(String(initial.maxChars));
  const [autoDelaySeconds, setAutoDelaySeconds] = useState(String(initial.autoDelaySeconds));
  const [intervalSeconds, setIntervalSeconds] = useState(String(initial.intervalSeconds));
  const [providers, setProviders] = useState<ProviderState[]>(
    initial.providers.map(providerState),
  );
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [testing, setTesting] = useState<number | null>(null);
  const [checks, setChecks] = useState<Partial<Record<1 | 2, ModelCheck[]>>>({});
  const busy = pending || testing !== null;

  function updateProvider(index: 1 | 2, changes: Partial<Pick<ProviderState, "baseUrl" | "models" | "apiKey">>) {
    setProviders((current) => current.map((provider) => (
      provider.index === index ? { ...provider, ...changes } : provider
    )));
    setChecks((current) => ({ ...current, [index]: undefined }));
  }

  function moveModel(provider: ProviderState, position: number, step: number) {
    const models = [...provider.models];
    const next = position + step;
    [models[position], models[next]] = [models[next], models[position]];
    updateProvider(provider.index, { models });
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
        providers: providers.map(({ index, baseUrl, models, apiKey }) => ({
          index, baseUrl, models: models.map((model) => model.trim()).filter(Boolean), apiKey,
        })),
      }),
    });
    setProviders(result.settings.providers.map(providerState));
    setMessage("AI-настройки сохранены.");
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
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
    setChecks((current) => ({ ...current, [index]: undefined }));
    setMessage("");
    setError("");
    try {
      await save();
      const created = await api<{ action: { id: string } }>("/api/ai/test", {
        method: "POST",
        body: JSON.stringify({ provider: index }),
      });
      for (let attempt = 0; attempt < 120; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 2500));
        const result = await api<{ action: { status: string; result: { reply?: string; models?: ModelCheck[] } | null; error: string | null } }>(`/api/actions/${created.action.id}`);
        if (result.action.status === "completed") {
          const summary = result.action.result;
          if (summary?.models) setChecks((current) => ({ ...current, [index]: summary.models }));
          setMessage(`Профиль ${index}: ${summary?.reply || "проверка завершена"}`);
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
          <fieldset key={provider.index} disabled={busy}>
            <legend>Профиль {provider.index}{provider.index === 2 ? " · резервный" : " · основной"}</legend>
            <label>Base URL<input aria-label={`Base URL провайдера ${provider.index}`} placeholder="https://api.example.com/v1" value={provider.baseUrl} onChange={(event) => updateProvider(provider.index, { baseUrl: event.target.value })} /></label>
            <div className="ai-model-list">
              <small>Один Base URL и ключ, до трёх моделей. Бот пробует их сверху вниз.</small>
              {provider.models.map((model, position) => (
                <div className="ai-model-row" key={position}>
                  <label>{position === 0 ? "Основная модель" : `Запасная модель ${position}`}
                    <input aria-label={`Модель ${position + 1} профиля ${provider.index}`} maxLength={200} placeholder="vision-model" value={model} onChange={(event) => updateProvider(provider.index, { models: provider.models.map((value, i) => i === position ? event.target.value : value) })} />
                  </label>
                  <div className="ai-model-controls">
                    <button type="button" aria-label={`Поднять модель ${position + 1} профиля ${provider.index}`} disabled={position === 0} onClick={() => moveModel(provider, position, -1)}>↑</button>
                    <button type="button" aria-label={`Опустить модель ${position + 1} профиля ${provider.index}`} disabled={position === provider.models.length - 1} onClick={() => moveModel(provider, position, 1)}>↓</button>
                    <button type="button" aria-label={`Удалить модель ${position + 1} профиля ${provider.index}`} disabled={provider.models.length === 1} onClick={() => updateProvider(provider.index, { models: provider.models.filter((_, i) => i !== position) })}>×</button>
                  </div>
                </div>
              ))}
              <button type="button" disabled={provider.models.length >= MAX_MODELS} onClick={() => updateProvider(provider.index, { models: [...provider.models, ""] })}>Добавить запасную модель</button>
            </div>
            <label>API-ключ<input aria-label={`API-ключ провайдера ${provider.index}`} type="password" autoComplete="new-password" placeholder={provider.hasKey ? "Оставьте пустым, чтобы не менять" : "sk-..."} value={provider.apiKey} onChange={(event) => updateProvider(provider.index, { apiKey: event.target.value })} /></label>
            {provider.hasKey ? <small className="success">Ключ сохранён</small> : <small>Ключ ещё не сохранён</small>}
            <button type="button" disabled={busy || !provider.baseUrl.trim() || !provider.models.some((model) => model.trim()) || (!provider.hasKey && !provider.apiKey.trim())} onClick={() => testProvider(provider.index)}>{testing === provider.index ? "Проверяю модели…" : `Проверить профиль ${provider.index}`}</button>
            {checks[provider.index]?.length ? (
              <ul className="ai-model-results" aria-label={`Проверка профиля ${provider.index}`} aria-live="polite">
                {checks[provider.index]?.map(({ model, ok, error }) => (
                  <li key={model}><strong>{model}</strong> — <span className={ok ? "success" : "error"}>{ok ? "Работает с изображениями" : error || "Не прошла проверку"}</span></li>
                ))}
              </ul>
            ) : null}
          </fieldset>
        ))}
      </div>
      <div className="form-grid ai-prompt-grid">
        <label>Максимум символов<input aria-label="Максимум символов AI-подписи" type="number" min="40" max="300" value={maxChars} onChange={(event) => setMaxChars(event.target.value)} /></label>
        <label>Задержка после добавления (сек)<input aria-label="Задержка AI" type="number" min="30" max="3600" value={autoDelaySeconds} onChange={(event) => setAutoDelaySeconds(event.target.value)} /></label>
        <label>Пауза между генерациями (сек)<input aria-label="Пауза AI" type="number" min="10" max="600" value={intervalSeconds} onChange={(event) => setIntervalSeconds(event.target.value)} /></label>
        <label className="wide">Техническое задание<textarea aria-label="Техническое задание для нейросети" rows={7} value={prompt} onChange={(event) => setPrompt(event.target.value)} /></label>
      </div>
      <div className="actions"><button className="primary" type="submit" disabled={busy}>{pending ? "Сохраняю…" : "Сохранить AI-настройки"}</button></div>
      {message ? <p className="success">{message}</p> : null}
      {error ? <p className="error" role="alert">{error}</p> : null}
    </form>
  );
}
