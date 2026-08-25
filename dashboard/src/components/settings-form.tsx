"use client";

import { FormEvent, useState } from "react";

import { api } from "@/lib/client-api";

type Settings = Partial<Record<
  "fresh_days" | "min_reactions" | "min_views" | "signature_text" | "signature_url",
  string
>>;

export function SettingsForm({ initial }: { initial: Settings }) {
  const [freshDays, setFreshDays] = useState(initial.fresh_days || "7");
  const [minReactions, setMinReactions] = useState(initial.min_reactions || "0");
  const [minViews, setMinViews] = useState(initial.min_views || "0");
  const [signatureText, setSignatureText] = useState(initial.signature_text || "НАШ ТГК");
  const [signatureUrl, setSignatureUrl] = useState(initial.signature_url || "https://t.me/webm4ik");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [probe, setProbe] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    const protocol = (() => { try { return new URL(signatureUrl).protocol; } catch { return ""; } })();
    if (protocol !== "http:" && protocol !== "https:") {
      setError("Ссылка подписи должна начинаться с http:// или https://");
      return;
    }
    setPending(true);
    try {
      await api("/api/settings", {
        method: "PUT",
        body: JSON.stringify({
          freshDays: Number(freshDays),
          minReactions: Number(minReactions),
          minViews: Number(minViews),
          signatureText,
          signatureUrl,
        }),
      });
      setMessage("Настройки сохранены.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Не удалось сохранить.");
    } finally {
      setPending(false);
    }
  }

  async function probeMax() {
    setProbe("Ставлю проверку в очередь…");
    try {
      const result = await api<{ action: { id: string } }>("/api/actions/max-probe", { method: "POST" });
      setProbe(`Проверка ожидает бота · ${result.action.id}`);
    } catch (reason) {
      setProbe(reason instanceof Error ? reason.message : "Ошибка MAX-проверки.");
    }
  }

  return (
    <form className="settings-form panel" onSubmit={submit}>
      <div className="form-grid">
        <label>Свежесть, дней<input aria-label="Свежесть, дней" type="number" min="1" max="90" value={freshDays} onChange={(event) => setFreshDays(event.target.value)} /></label>
        <label>Минимум реакций<input aria-label="Минимум реакций" type="number" min="0" max="1000000" value={minReactions} onChange={(event) => setMinReactions(event.target.value)} />{Number(minReactions) === 0 ? <small>без ограничения</small> : null}</label>
        <label>Минимум просмотров<input aria-label="Минимум просмотров" type="number" min="0" max="1000000" value={minViews} onChange={(event) => setMinViews(event.target.value)} />{Number(minViews) === 0 ? <small>без ограничения</small> : null}</label>
        <label>Текст подписи<input aria-label="Текст подписи" value={signatureText} onChange={(event) => setSignatureText(event.target.value)} /></label>
        <label className="wide">Ссылка подписи<input aria-label="Ссылка подписи" value={signatureUrl} onChange={(event) => setSignatureUrl(event.target.value)} /></label>
      </div>
      <div className="actions">
        <button type="submit" className="primary" disabled={pending}>{pending ? "Сохраняю…" : "Сохранить настройки"}</button>
        <button type="button" onClick={probeMax}>Проверить MAX</button>
      </div>
      {message ? <p className="success">{message}</p> : null}
      {probe ? <p>{probe}</p> : null}
      {error ? <p className="error" role="alert">{error}</p> : null}
    </form>
  );
}
