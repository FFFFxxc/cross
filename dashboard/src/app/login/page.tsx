"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

export default function LoginPage() {
  const router = useRouter();
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError("");
    const form = new FormData(event.currentTarget);
    const response = await fetch("/api/session/login", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ password: form.get("password") }),
    });
    if (response.ok) {
      router.push("/");
      router.refresh();
      return;
    }
    setPending(false);
    setError("Не удалось войти. Проверьте пароль и попробуйте снова.");
  }

  return (
    <main>
      <form onSubmit={submit}>
        <h1>Desiree</h1>
        <p>Панель управления публикациями</p>
        <label htmlFor="password">Пароль</label>
        <input id="password" name="password" type="password" required autoFocus />
        <button type="submit" disabled={pending}>
          {pending ? "Вхожу…" : "Войти"}
        </button>
        {error ? <p role="alert">{error}</p> : null}
      </form>
    </main>
  );
}
