"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/client-api";
import { SettingsForm } from "./settings-form";

export function SettingsLoader() {
  const [settings, setSettings] = useState<Record<string, string> | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api<{ settings: Record<string, string> }>("/api/settings")
      .then((result) => setSettings(result.settings))
      .catch((reason) => setError(reason instanceof Error ? reason.message : "Не удалось загрузить настройки."));
  }, []);
  if (error) return <p className="notice error" role="alert">{error}</p>;
  if (!settings) return <p className="notice">Загружаю настройки…</p>;
  return <SettingsForm initial={settings} />;
}
