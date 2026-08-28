"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/client-api";
import { AiSettingsForm, type AiSettingsView } from "./ai-settings-form";

export function AiSettingsLoader() {
  const [settings, setSettings] = useState<AiSettingsView | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api<{ settings: AiSettingsView }>("/api/ai/settings")
      .then((result) => setSettings(result.settings))
      .catch((reason) => setError(reason instanceof Error ? reason.message : "Не удалось загрузить AI-настройки."));
  }, []);
  if (error) return <p className="notice error" role="alert">{error}</p>;
  if (!settings) return <p className="notice">Загружаю AI-настройки…</p>;
  return <AiSettingsForm initial={settings} />;
}
