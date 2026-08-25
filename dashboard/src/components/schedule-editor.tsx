"use client";

import { useMemo, useState } from "react";

import { api } from "@/lib/client-api";

type Slot = { time: string; mediaKind: string; source: string | null };
type Source = { peer: string; title: string };
const TIME = /^(?:[01]\d|2[0-3]):[0-5]\d$/;

export function ScheduleEditor({ initialSlots, sources }: { initialSlots: Slot[]; sources: Source[] }) {
  const [slots, setSlots] = useState(() => [...initialSlots].sort((a, b) => a.time.localeCompare(b.time)));
  const [newTime, setNewTime] = useState("");
  const [error, setError] = useState("");
  const ordered = useMemo(() => [...slots].sort((a, b) => a.time.localeCompare(b.time)), [slots]);

  function update(time: string, patch: Partial<Slot>) {
    setSlots((values) => values.map((slot) => slot.time === time ? { ...slot, ...patch } : slot));
  }

  async function save(slot: Slot) {
    setError("");
    try {
      await api("/api/schedule", { method: "PUT", body: JSON.stringify(slot) });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Не удалось сохранить слот.");
    }
  }

  async function remove(time: string) {
    await api(`/api/schedule/${encodeURIComponent(time)}`, { method: "DELETE" });
    setSlots((values) => values.filter((slot) => slot.time !== time));
  }

  function add() {
    if (!TIME.test(newTime)) {
      setError("Укажите время как ЧЧ:ММ.");
      return;
    }
    if (slots.some((slot) => slot.time === newTime)) {
      setError("Такой слот уже есть.");
      return;
    }
    setSlots((values) => [...values, { time: newTime, mediaKind: "any", source: null }]);
    setNewTime("");
    setError("");
  }

  return (
    <div className="schedule-editor">
      <div className="new-slot panel">
        <label>Новое время<input aria-label="Новое время" placeholder="14:00" value={newTime} onChange={(event) => setNewTime(event.target.value)} /></label>
        <button type="button" className="primary" onClick={add}>Добавить слот</button>
      </div>
      {error ? <p role="alert" className="error">{error}</p> : null}
      <div className="slot-list">
        {ordered.map((slot) => (
          <div className="slot-row panel" key={slot.time}>
            <strong data-testid="slot-time">{slot.time}</strong>
            <label>Тип поста<select aria-label="Тип поста" value={slot.mediaKind} onChange={(event) => update(slot.time, { mediaKind: event.target.value })}><option value="any">Любой</option><option value="video">Видео</option><option value="image">Картинка</option></select></label>
            <label>Источник<select aria-label="Источник слота" value={slot.source || ""} onChange={(event) => update(slot.time, { source: event.target.value || null })}><option value="">Любой</option>{sources.map((source) => <option key={source.peer} value={source.peer}>{source.title}</option>)}</select></label>
            <button type="button" className="primary" onClick={() => save(slot)}>Сохранить</button>
            <button type="button" onClick={() => remove(slot.time)}>Удалить</button>
          </div>
        ))}
      </div>
    </div>
  );
}
