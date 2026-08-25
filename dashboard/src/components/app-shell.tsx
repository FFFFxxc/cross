"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

const LINKS = [
  ["/", "Главная"],
  ["/queue", "Очередь"],
  ["/sources", "Источники"],
  ["/schedule", "Расписание"],
  ["/settings", "Настройки"],
  ["/activity", "События"],
] as const;

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  return (
    <div className="app-layout">
      <header className="topbar">
        <Link href="/" className="brand">Desiree</Link>
        <span className="brand-subtitle">Telegram → MAX</span>
      </header>
      <nav className="nav" aria-label="Основная навигация">
        {LINKS.map(([href, label]) => (
          <Link key={href} href={href} className={pathname === href ? "active" : ""}>
            {label}
          </Link>
        ))}
      </nav>
      <main className="content">{children}</main>
    </div>
  );
}
