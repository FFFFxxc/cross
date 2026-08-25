import { NextResponse } from "next/server";

import {
  createSessionCookie,
  requireSameOrigin,
  verifyPassword,
} from "@/lib/auth";
import { getEnv } from "@/lib/env";

type Attempt = { failures: number; blockedUntil: number };
const attempts = new Map<string, Attempt>();

function clientIp(request: Request): string {
  return request.headers.get("x-forwarded-for")?.split(",")[0]?.trim() || "unknown";
}

export async function POST(request: Request) {
  try {
    requireSameOrigin(request);
  } catch {
    return NextResponse.json({ error: "Запрос отклонён." }, { status: 403 });
  }

  const ip = clientIp(request);
  const now = Date.now();
  const current = attempts.get(ip) ?? { failures: 0, blockedUntil: 0 };
  if (current.blockedUntil > now || current.failures >= 5) {
    return NextResponse.json(
      { error: "Слишком много попыток. Попробуйте позже." },
      { status: 429 },
    );
  }

  let password = "";
  try {
    const body = (await request.json()) as { password?: unknown };
    password = typeof body.password === "string" ? body.password : "";
  } catch {
    // Use the same generic authentication failure below.
  }

  let valid = false;
  try {
    valid = await verifyPassword(password, getEnv().ADMIN_PASSWORD_HASH);
  } catch {
    valid = false;
  }
  if (!valid) {
    const failures = current.failures + 1;
    attempts.set(ip, {
      failures,
      blockedUntil: failures >= 5 ? now + 60_000 : 0,
    });
    return NextResponse.json({ error: "Неверный пароль." }, { status: 401 });
  }

  attempts.delete(ip);
  const session = await createSessionCookie();
  const response = NextResponse.json({ ok: true });
  response.cookies.set(session.name, session.value, session.options);
  return response;
}
