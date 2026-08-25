"use client";

import { useState } from "react";

export function ActionButton({
  label,
  pendingLabel,
  className,
  onAction,
}: {
  label: string;
  pendingLabel: string;
  className?: string;
  onAction: () => Promise<void>;
}) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  async function run() {
    if (pending) return;
    setPending(true);
    setError("");
    try {
      await onAction();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Ошибка действия.");
      setPending(false);
    }
  }
  return (
    <span className="action-wrap">
      <button type="button" className={className} onClick={run} disabled={pending}>
        {pending ? pendingLabel : label}
      </button>
      {error ? <small role="alert">{error}</small> : null}
    </span>
  );
}
